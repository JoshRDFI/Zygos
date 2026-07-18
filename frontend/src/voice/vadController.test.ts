import { expect, test } from "vitest";
import { VadController, type VadSignal } from "./vadController";

function make(confirmFrames = 3) {
  const signals: VadSignal[] = [];
  const c = new VadController({ emit: (s) => signals.push(s), confirmFrames });
  return { c, signals };
}

test("onSpeechStart emits onset immediately", () => {
  const { c, signals } = make();
  c.onSpeechStart();
  expect(signals).toEqual(["onset"]);
});

test("emits speech once after N consecutive speech frames, then never again", () => {
  const { c, signals } = make(3);
  c.onSpeechStart();
  c.onFrame(true);
  c.onFrame(true);
  expect(signals).toEqual(["onset"]);   // not yet confirmed
  c.onFrame(true);                        // 3rd consecutive -> confirm
  expect(signals).toEqual(["onset", "speech"]);
  c.onFrame(true);                        // no re-emit
  c.onFrame(true);
  expect(signals).toEqual(["onset", "speech"]);
});

test("a non-speech frame resets the consecutive counter", () => {
  const { c, signals } = make(3);
  c.onSpeechStart();
  c.onFrame(true);
  c.onFrame(true);
  c.onFrame(false);   // reset
  c.onFrame(true);
  c.onFrame(true);
  expect(signals).toEqual(["onset"]);  // only 2 consecutive since reset -> no speech
});

test("onMisfire before confirm emits silence and no speech", () => {
  const { c, signals } = make(8);
  c.onSpeechStart();
  c.onFrame(true);
  c.onMisfire();
  expect(signals).toEqual(["onset", "silence"]);
});

test("onSpeechEnd emits silence", () => {
  const { c, signals } = make(1);
  c.onSpeechStart();
  c.onFrame(true);   // confirm
  c.onSpeechEnd();
  expect(signals).toEqual(["onset", "speech", "silence"]);
});

test("frames before onSpeechStart are ignored", () => {
  const { c, signals } = make(1);
  c.onFrame(true);
  c.onFrame(true);
  expect(signals).toEqual([]);
});

test("onSpeechEnd without an active utterance is a no-op", () => {
  const { c, signals } = make();
  c.onSpeechEnd();
  expect(signals).toEqual([]);
});
