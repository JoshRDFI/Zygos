// frontend/src/voice/worklet/capture-processor.js
// Minimal AudioWorkletProcessor: forwards raw mono Float32 frames to the main
// thread. All resampling/encoding happens on the main thread (kept testable).
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length) {
      // Copy: the underlying buffer is reused by the audio thread each block.
      this.port.postMessage(input[0].slice(0));
    }
    return true;
  }
}
registerProcessor("capture-processor", CaptureProcessor);
