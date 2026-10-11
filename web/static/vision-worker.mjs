let meshRatios;
let detector;
self.onmessage = async ({ data }) => {
  try {
    if (data.type === 'init') {
      // Classic worker permits the WASM loader's importScripts call.
      const { FaceLandmarker, FilesetResolver } = await import('./vendor/vision_bundle.mjs');
      ({ meshRatios } = await import('./model-features.mjs'));
      const vision = await FilesetResolver.forVisionTasks(new URL('./vendor/wasm', self.location.href).href);
      detector = await FaceLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: new URL('./vendor/face_landmarker.task', self.location.href).href, delegate: 'CPU' },
        runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true,
        minFaceDetectionConfidence: 0.6, minFacePresenceConfidence: 0.6, minTrackingConfidence: 0.6,
      });
      self.postMessage({ type: 'ready' });
    } else if (data.type === 'frame' && detector) {
      const start = performance.now();
      try {
        const result = detector.detectForVideo(data.bitmap, data.t);
        const scores = result.faceBlendshapes?.[0]?.categories;
        const find = name => scores?.find(s => s.categoryName === name)?.score;
        const left = find('eyeBlinkLeft'), right = find('eyeBlinkRight');
        const closure = Number.isFinite(left) && Number.isFinite(right) ? (left + right) / 2 : null;
        const points = result.faceLandmarks?.[0];
        self.postMessage({ type: 'result', t: data.t, closure, ms: performance.now() - start,
          ratios: meshRatios(points, data.bitmap.width, data.bitmap.height),
          points: points ? [33, 133, 159, 145, 362, 263, 386, 374, 1, 61, 291].map(i => points[i]) : [] });
      } finally { data.bitmap.close(); }
    }
  } catch (error) {
    self.postMessage({ type: 'error', message: error.message || String(error) });
  }
};
