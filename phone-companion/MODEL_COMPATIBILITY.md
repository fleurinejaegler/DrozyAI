# Existing src model: inspected compatibility

The existing prediction entry point is `src/models/predict.py` (`load_model`, `predict_score`). The trained artifact exists at `data/processed/baseline_model.pkl`. Training and preprocessing are in `src/models/baseline.py`, `src/features/watch_features.py`, and `src/data/loader.py`. These files were inspected and left unchanged.

`local-relay/repo_model_adapter.py` now imports the real prediction function for complete, matching feature dictionaries. It reads feature order from the source and caches the existing model; it does not create/train/replace a model. Its Garmin path deliberately returns null risk and insufficient_data because the current training contract cannot be satisfied by the watch.

| Model feature, in order | Existing training definition | Garmin compatibility |
| --- | --- | --- |
| hr_mean | Mean of per-second heart_rate across a 60-row window | Available signal, but a matching 60-second window/coverage policy is needed |
| rmssd | RMS successive differences of per-second ibi_mean values where ibi_count > 0 | Different from the watch's beat-level RMSSD; interval units and matching preprocessing must be established |
| temp_trend | Slope of skin-temperature values against their compacted sample index after dropping NaNs | Watch Sensor.Info temperature is not identified as skin temperature; not an equivalent replacement |
| eda_peaks | Peaks in EDA above window mean + standard deviation | Unavailable from the Garmin feed; must not be filled with zero or invented |
| motion_var | Mean of per-second variances for the three accelerometer axes | Training loader aggregates 32 Hz source samples; units/scaling and rate conversion to Garmin mg batches must be established |

The current model ignores SpO₂ and gyroscope. Temperature and HRV being present in a packet does not resolve their training-contract mismatch. The source does not declare all physical units explicitly, so example values are not a reliable feature schema. No conversion was guessed.

## Use the adapter

From the repository root, with Python 3.10+:

```sh
python phone-companion/local-relay/repo_model_adapter.py
```

This prints the source feature order and compatibility reasons without requiring ML dependencies or executing the artifact. In your teammate's Python process, add `phone-companion/local-relay` to the import path and use `RepoModelAdapter().evaluate_prepared_features(features)` only when `features` comes from matching training preprocessing. It calls `src.models.predict.predict_score` unchanged and requires all finite inputs. The result envelope can be sent through `RelayClient.send_model_result` using the original telemetry snapshot/capture time.

`send_garmin_result(relay, snapshot)` sends the honest null/insufficient-data state for the current model. This is not model-based detection. The phone/watch telemetry, manual camera alerts, alarms, and acknowledgment still work. The inference dependency environment must include the model's matching numpy/joblib/scikit-learn versions; the adapter does not alter the root requirements.

## Required teammate change

Provide or retrain a Garmin-compatible model that excludes unavailable EDA and unsupported skin-temperature features, with exact feature names/order, units, sampling/window coverage, missing-data policy, and reference input/output examples. Decide whether to retain the existing per-second IBI-mean definition or train against genuine beat-level RMSSD, and validate transfer from UL-DD accelerometer data to Garmin units/rates. Do not simply delete two input columns from the existing fitted model.

The training source saves RobustScaler + HistGradientBoostingClassifier as its final pipeline. Isotonic calibration is used for the cross-validation score table but is not included in that final saved pipeline by the shown training code. Therefore the prediction module's claim of calibrated probabilities needs review before treating thresholds/probability meanings as validated.

The video feature/fusion/GRU/calibration files inspected in src are currently empty placeholders; no executable video classifier was found there. Website camera/manual alert transport is implemented independently of that missing classifier.

Validation limit: no Python executable is available in this Windows shell. The adapter and actual fitted model have not been executed here. Existing Node relay tests and watch builds/tests remain separate from model-inference validation; run the adapter and matching-model reference tests in your Python environment.
