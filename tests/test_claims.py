import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, User, Work
from app.repository import (
    CLAIM_TTL,
    all_users,
    claim,
    cookie_value,
    is_claimed,
    next_free_at,
    profile_works,
    resolve_cookie,
    utcnow,
    works_count,
)


def identity(slug: str, position: int) -> User:
    return User(
        slug=slug,
        name=slug,
        handle=f"@{slug}",
        bio="",
        avatar_fill="ffffff",
        saved_count=0,
        level=1,
        xp=0,
        xp_goal=1000,
        position=position,
    )


def work(title: str, position: int, user: User | None, status: str = "live") -> Work:
    # position doubles as upload order: a higher position is a newer upload.
    return Work(
        title=title,
        author=user.name if user else "nobody",
        category="relax",
        emoji="🎮",
        art="art-one",
        views="0",
        likes="0",
        collection="feed",
        position=0,
        status=status,
        created_at=datetime(2026, 9, 23, 12, position),
        user_id=user.id if user else None,
    )


class ClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([identity("bee-1", 0), identity("bee-2", 1)])
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def user(self, slug: str) -> User:
        return self.session.query(User).filter_by(slug=slug).one()

    def test_claiming_a_free_identity_returns_a_token(self) -> None:
        self.assertIsNotNone(claim(self.session, "bee-1"))
        self.assertTrue(is_claimed(self.user("bee-1")))

    def test_the_house_account_cannot_be_claimed_or_listed(self) -> None:
        house = identity("beeplay", 2)
        house.claimable = False
        self.session.add(house)
        self.session.commit()

        self.assertIsNone(claim(self.session, "beeplay"))
        self.assertNotIn("beeplay", [user.slug for user in all_users(self.session)])

    def test_claiming_a_taken_identity_fails(self) -> None:
        claim(self.session, "bee-1")
        self.assertIsNone(claim(self.session, "bee-1"))

    def test_reclaiming_your_own_identity_keeps_the_same_token(self) -> None:
        token = claim(self.session, "bee-1")
        holder = self.user("bee-1")
        self.assertEqual(claim(self.session, "bee-1", holder), token)

    def test_switching_releases_the_previous_identity(self) -> None:
        claim(self.session, "bee-1")
        holder = self.user("bee-1")
        self.assertIsNotNone(claim(self.session, "bee-2", holder))
        self.assertFalse(is_claimed(self.user("bee-1")))

    def test_a_stale_switch_cannot_reserve_another_identity(self) -> None:
        self.session.add(identity("bee-3", 2))
        self.session.commit()
        claim(self.session, "bee-1")
        stale_session = Session(self.engine)
        stale_holder = stale_session.query(User).filter_by(slug="bee-1").one()

        # A first request has already switched away from bee-1. A concurrent
        # request still holding its old ORM value must roll back its new claim.
        try:
            self.assertIsNotNone(claim(self.session, "bee-2", self.user("bee-1")))
            self.assertIsNone(claim(stale_session, "bee-3", stale_holder))
        finally:
            stale_session.close()
        self.session.expire_all()
        self.assertFalse(is_claimed(self.user("bee-3")))

    def test_a_stale_claim_is_claimable_again(self) -> None:
        claim(self.session, "bee-1")
        self.user("bee-1").last_seen_at = utcnow() - CLAIM_TTL - timedelta(minutes=1)
        self.session.commit()
        self.assertIsNotNone(claim(self.session, "bee-2"))  # unrelated, still free
        self.assertIsNotNone(claim(self.session, "bee-1"))

    def test_next_free_at_is_none_while_an_identity_is_free(self) -> None:
        claim(self.session, "bee-1")
        self.assertIsNone(next_free_at(self.session))

    def test_next_free_at_reports_the_longest_idle_claim(self) -> None:
        claim(self.session, "bee-1")
        oldest = utcnow() - timedelta(hours=1)
        self.user("bee-1").last_seen_at = oldest
        self.session.commit()
        claim(self.session, "bee-2")
        self.assertEqual(next_free_at(self.session), oldest + CLAIM_TTL)


class CookieTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([identity("bee-1", 0), identity("bee-2", 1)])
        self.session.commit()
        self.token = claim(self.session, "bee-1")

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_a_matching_cookie_resolves_to_its_user(self) -> None:
        user, status = resolve_cookie(self.session, cookie_value("bee-1", self.token))
        self.assertEqual(status, "ok")
        self.assertEqual(user.slug, "bee-1")

    def test_a_missing_or_malformed_cookie_is_anonymous(self) -> None:
        for raw in (None, "", "bee-1", "nope.abcd"):
            self.assertEqual(resolve_cookie(self.session, raw), (None, "anonymous"))

    def test_an_identity_taken_by_someone_else_reports_stolen(self) -> None:
        stale = cookie_value("bee-1", self.token)
        user = self.session.query(User).filter_by(slug="bee-1").one()
        user.last_seen_at = utcnow() - CLAIM_TTL - timedelta(minutes=1)
        self.session.commit()
        claim(self.session, "bee-1")  # a second tester takes it

        self.assertEqual(resolve_cookie(self.session, stale), (None, "stolen"))

    def test_an_expired_claim_nobody_took_is_picked_back_up(self) -> None:
        raw = cookie_value("bee-1", self.token)
        user = self.session.query(User).filter_by(slug="bee-1").one()
        user.last_seen_at = utcnow() - CLAIM_TTL - timedelta(minutes=1)
        self.session.commit()

        resolved, status = resolve_cookie(self.session, raw)
        self.assertEqual(status, "ok")
        self.assertTrue(is_claimed(resolved))


class ProfileWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.one, self.two = identity("bee-1", 0), identity("bee-2", 1)
        self.session.add_all([self.one, self.two])
        self.session.commit()
        self.session.add_all(
            [
                work("Mine A", 0, self.one),
                work("Mine B", 1, self.one),
                work("Theirs", 0, self.two),
                work("Orphan", 2, None),
                work("Mine, crashing", 3, self.one, status="hidden"),
                work("Mine, deleted", 4, self.one, status="deleted"),
            ]
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_profile_shows_that_users_undeleted_uploads_newest_first(self) -> None:
        # Hidden stays visible to its owner so the crash banner can show.
        self.assertEqual(
            [w.title for w in profile_works(self.session, self.one)],
            ["Mine, crashing", "Mine B", "Mine A"],
        )

    def test_works_count_matches_what_the_grid_shows(self) -> None:
        self.assertEqual(works_count(self.session, self.one), 3)
        self.assertEqual(works_count(self.session, self.two), 1)


if __name__ == "__main__":
    unittest.main()
