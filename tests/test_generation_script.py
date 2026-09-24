"""Exercise the real preview message handler's asynchronous failure handling."""
import subprocess
import unittest
from pathlib import Path


class GenerationScriptTests(unittest.TestCase):
    def test_load_callback_cannot_hide_a_crash_or_affect_a_reopened_frame(self):
        source = (Path(__file__).parents[1] / 'assets/js/generation.js').read_text()
        handler = source[source.index('  window.addEventListener("message"'):source.index('  function startOver()')]
        harness = r'''
const assert = require('node:assert/strict');
let listener, resolveLoad, message;
let button = {disabled:true};
let frame = {contentWindow:{}}, previewJob='job', previewFailed=false;
let previewStart=0, loadTimer;
const overlay={querySelector:()=>button};
const window={addEventListener:(name,fn)=>{listener=fn;}};
const signal=(kind)=>kind==='playtest_loaded' ? new Promise(r=>resolveLoad=r) : Promise.resolve();
const previewMessage=text=>{message=text;};
const previewProblem=previewMessage;
const send=kind=>listener({source:frame.contentWindow,data:{beeplay:kind}});
'''
        checks = r'''
(async()=>{
  send('loaded'); send('error'); const errorMessage=message;
  resolveLoad(); await Promise.resolve();
  assert.equal(button.disabled,true); assert.equal(message,errorMessage);
  previewFailed=false; send('loaded'); resolveLoad(); await Promise.resolve();
  assert.equal(button.disabled,false);
  send('error'); assert.equal(button.disabled,true);
  previewFailed=false; send('loaded');
  frame={contentWindow:{}}; button.disabled=true;
  resolveLoad(); await Promise.resolve(); assert.equal(button.disabled,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', harness + handler + checks], check=True)
