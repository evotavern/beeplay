const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const outputDir = path.resolve(__dirname, "../assets/icons");
const logoReference = path.resolve(__dirname, "../assets/brand/beeplay-logo-reference.png");
fs.mkdirSync(outputDir, { recursive: true });

const ink = "#171b1a";
const lime = "#b5d65a";
const cream = "#f8fbe8";
const orange = "#f27c45";
const lavender = "#d8d6ff";
const beeYellow = "#f8df2f";
const wingGray = "#d4d5d4";

const wrap = (content, size = 128) => `
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 128 128" fill="none">
  ${content}
</svg>`;

const icons = {
  "beeplay-logo": {
    size: 512,
    svg: (size) => `
      <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 512 512" fill="none">
        <rect x="8" y="8" width="496" height="496" rx="168" fill="${ink}"/>
        <path d="M135 285c-12-76 30-133 101-150 79-18 151 25 180 91-26 58-90 96-169 93-41-2-79-13-112-34Z" fill="${beeYellow}" stroke="${ink}" stroke-width="18" stroke-linejoin="round"/>
        <path d="M161 258c-45-48-49-111-15-144 31-31 79-21 102 15 24 37 15 93-28 135" fill="${wingGray}" stroke="${ink}" stroke-width="18" stroke-linejoin="round"/>
        <path d="M142 276c-61-23-112-9-128 28-17 40 23 66 77 56 47-8 84-31 110-62" fill="${wingGray}" stroke="${ink}" stroke-width="18" stroke-linejoin="round"/>
        <path d="M185 342c-38 40-65 79-88 127 63-37 111-77 139-116" fill="${ink}" stroke="${ink}" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M186 282c-9 39-1 78 22 113" stroke="${ink}" stroke-width="24" stroke-linecap="round"/>
        <path d="M242 255c-12 45-3 88 25 126" stroke="${ink}" stroke-width="22" stroke-linecap="round"/>
        <path d="M313 196c12 6 27 5 38-4M337 220c13 5 27 3 37-6" stroke="${ink}" stroke-width="12" stroke-linecap="round"/>
        <path d="M300 269c17 14 37 12 50-2" stroke="${ink}" stroke-width="10" stroke-linecap="round"/>
        <path d="m239 291 34 20-34 20v-40Z" fill="${ink}"/>
      </svg>
    `,
  },
  "beeplay-mascot": {
    size: 640,
    svg: (size) => `
      <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 640 640" fill="none">
        <path d="M145 320c-19-76 16-151 91-178 85-31 189 11 223 94-18 92-102 145-214 143-40-1-74-17-100-59Z" fill="${beeYellow}" stroke="${ink}" stroke-width="22" stroke-linejoin="round"/>
        <path d="M187 269c-52-55-53-139-10-178 39-36 101-18 128 31 25 46 8 111-39 153" fill="${wingGray}" stroke="${ink}" stroke-width="22" stroke-linejoin="round"/>
        <path d="M160 304c-84-30-151-2-158 48-6 47 53 65 117 42 52-19 94-50 119-91" fill="${wingGray}" stroke="${ink}" stroke-width="22" stroke-linejoin="round"/>
        <path d="M175 371c-58 52-94 109-128 184 82-48 144-99 182-160" fill="${ink}" stroke="${ink}" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M188 314c-12 47-3 93 27 135" stroke="${ink}" stroke-width="28" stroke-linecap="round"/>
        <path d="M269 280c-15 52-5 103 29 150" stroke="${ink}" stroke-width="27" stroke-linecap="round"/>
        <path d="M378 195c14 7 32 4 45-8M407 226c16 6 33 2 44-10" stroke="${ink}" stroke-width="15" stroke-linecap="round"/>
        <path d="M365 285c22 18 50 16 67-3" stroke="${ink}" stroke-width="13" stroke-linecap="round"/>
        <circle cx="330" cy="312" r="44" fill="${cream}" opacity=".65"/>
        <path d="m313 286 37 26-37 26v-52Z" fill="${ink}"/>
      </svg>
    `,
  },
  "home": {
    size: 128,
    svg: () => wrap(`<path d="m18 60 46-42 46 42" stroke="${ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/><path d="M28 54v54h72V54M50 108V78h28v30" stroke="${ink}" stroke-width="9" stroke-linejoin="round"/>`),
  },
  "discover": {
    size: 128,
    svg: () => wrap(`<circle cx="64" cy="64" r="45" stroke="${ink}" stroke-width="9"/><path d="m81 47-11 25-25 11 11-25 25-11Z" stroke="${ink}" stroke-width="8" stroke-linejoin="round"/>`),
  },
  "create": {
    size: 128,
    svg: () => wrap(`<circle cx="64" cy="64" r="55" fill="${lime}"/><path d="M64 34v60M34 64h60" stroke="${ink}" stroke-width="10" stroke-linecap="round"/>`),
  },
  "messages": {
    size: 128,
    svg: () => wrap(`<path d="M64 17c8 15 16 23 31 31-15 8-23 16-31 31-8-15-16-23-31-31 15-8 23-16 31-31Z" stroke="${ink}" stroke-width="7" stroke-linejoin="round"/><path d="M21 77c7 9 14 14 24 18-10 4-17 9-24 18-4-9-9-14-18-18 9-4 14-9 18-18ZM107 77c4 9 9 14 18 18-9 4-14 9-18 18-7-9-14-14-24-18 10-4 17-9 24-18Z" fill="${lime}" stroke="${ink}" stroke-width="5"/>`),
  },
  "profile": {
    size: 128,
    svg: () => wrap(`<circle cx="64" cy="42" r="22" fill="${ink}"/><path d="M25 111c6-31 21-49 39-49s33 18 39 49" fill="${orange}"/><circle cx="55" cy="37" r="5" fill="${cream}"/>`),
  },
  "notification": {
    size: 128,
    svg: () => wrap(`<path d="M96 57c0-20-14-36-32-36S32 37 32 57c0 29-12 35-12 45h88c0-10-12-16-12-45Z" stroke="${ink}" stroke-width="8" stroke-linejoin="round"/><path d="M55 112h18" stroke="${ink}" stroke-width="8" stroke-linecap="round"/>`),
  },
  "play": {
    size: 128,
    svg: () => wrap(`<circle cx="64" cy="64" r="54" fill="${lime}"/><path d="m53 36 38 28-38 28V36Z" fill="${ink}"/>`),
  },
  "like": {
    size: 128,
    svg: () => wrap(`<path d="M64 106 22 66c-19-19-7-50 18-50 13 0 21 8 24 17 3-9 11-17 24-17 25 0 37 31 18 50l-42 40Z" fill="${orange}"/>`),
  },
  "save": {
    size: 128,
    svg: () => wrap(`<path d="M29 18h70v93l-35-22-35 22V18Z" fill="${lavender}" stroke="${ink}" stroke-width="8" stroke-linejoin="round"/>`),
  },
  "share": {
    size: 128,
    svg: () => wrap(`<circle cx="35" cy="64" r="13" fill="${lime}" stroke="${ink}" stroke-width="7"/><circle cx="94" cy="31" r="13" fill="${lime}" stroke="${ink}" stroke-width="7"/><circle cx="94" cy="97" r="13" fill="${lime}" stroke="${ink}" stroke-width="7"/><path d="m46 59 37-21M46 69l37 21" stroke="${ink}" stroke-width="8" stroke-linecap="round"/>`),
  },
  "search": {
    size: 128,
    svg: () => wrap(`<circle cx="55" cy="55" r="31" stroke="${ink}" stroke-width="8"/><path d="m78 78 28 28" stroke="${ink}" stroke-width="8" stroke-linecap="round"/>`),
  },
  "close": {
    size: 128,
    svg: () => wrap(`<circle cx="64" cy="64" r="54" fill="${cream}"/><path d="m40 40 48 48M88 40 40 88" stroke="${ink}" stroke-width="9" stroke-linecap="round"/>`),
  },
  "more": {
    size: 128,
    svg: () => wrap(`<circle cx="32" cy="64" r="9" fill="${ink}"/><circle cx="64" cy="64" r="9" fill="${ink}"/><circle cx="96" cy="64" r="9" fill="${ink}"/>`),
  },
};

(async () => {
  for (const [name, icon] of Object.entries(icons)) {
    if (name === "beeplay-logo" && fs.existsSync(logoReference)) continue;
    const svg = Buffer.from(icon.svg(icon.size));
    await sharp(svg).png().toFile(path.join(outputDir, `${name}.png`));
  }
  if (fs.existsSync(logoReference)) {
    await sharp(logoReference)
      .trim({ background: { r: 255, g: 255, b: 255 }, threshold: 8 })
      .resize(512, 512, { fit: "fill" })
      .png()
      .toFile(path.join(outputDir, "beeplay-logo.png"));
  }
  fs.writeFileSync(
    path.join(outputDir, "manifest.json"),
    JSON.stringify(
      Object.fromEntries(Object.entries(icons).map(([name, icon]) => [name, {
        file: `${name}.png`,
        width: icon.size,
        height: icon.size,
        background: "transparent",
      }])),
      null,
      2,
    ) + "\n",
  );
  console.log(`Exported ${Object.keys(icons).length} PNG icons to ${outputDir}`);
})();
