# Uplink schema 1

`POST /garmin/data`, `Content-Type: application/json`,
`Authorization: Bearer <token>`. The watch uses an HTTPS URL. All requests have:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer 1 |
| `device` | `garmin_forerunner_970` (device class, not hardware serial) |
| `session` | New UTC/random identifier for each watch app instance |
| `batch_id` | Increasing positive integer, unchanged on retry |
| `anchor_epoch_s` | Watch UTC at session start, integer seconds |
| `anchor_watch_ms` | Watch callback-clock uptime at the anchor |
| `created_watch_ms` | Time the immutable batch was sealed |
| `heart_rate` | Ordered `{t, v}` observations; `v` BPM or null |
| `accelerometer` | Ordered `{t, rate_hz, x, y, z, sensor_ms}` callback blocks |
| `ibi` | Ordered `{t, values_ms}` callback blocks, raw ms/null values |
| `temperature` | `{t, v, source, type, epoch_s}` observations; Celsius/null |
| `availability` | Current status of all four sensor groups |
| `dropped` | Cumulative loss counters for the session |

Every `t` is a callback/poll `System.getTimer()` value in ms, **not** individual
IBI beat time. ACC arrays have equal lengths, retain positions/nulls and original
API sensor timestamps, and use native device axes in mg. Temperature sources are
`watch_onboard_history` or `watch_sensor_info_no_external`; type is `unknown`
in this implementation. `epoch_s` is the history observation's UTC timestamp,
otherwise null. No sensor frame transform or unit conversion is done on the watch.

Availability values are `receiving` or `unavailable`; HR/IBI/temperature can also
be `external_blocked`. A `receiving` status reflects received data, not hardware
validation or measurement accuracy. Temperature history may be slower than HR.
The status snapshot can be newer than buffered observations in the same batch.

Loss keys are `heart_rate`, `accelerometer`, `ibi`, `temperature` (observation/
sample/interval counts) and `expired_batches`. Cumulative values are frozen into
the batch alongside its samples. Continuing collection never mutates a retry.

ACK, on successful durable storage:

```json
{"status":"accepted","session":"THE_SESSION","batch_id":1}
```

An exact accepted retry returns the same shape with `status: duplicate`.
The watch accepts only HTTP 200 with a matching session and ID. This ACK confirms
receiver acceptance, not model classification or any alarm action.

The following is an **empty manual schema illustration**, not real watch data:

```json
{
  "schema_version": 1,
  "device": "garmin_forerunner_970",
  "session": "offline-empty-example",
  "batch_id": 1,
  "anchor_epoch_s": 1791690000,
  "anchor_watch_ms": 1000,
  "created_watch_ms": 6000,
  "heart_rate": [],
  "accelerometer": [],
  "ibi": [],
  "temperature": [],
  "availability": {
    "heart_rate": "unavailable",
    "accelerometer": "unavailable",
    "ibi": "unavailable",
    "temperature": "unavailable"
  },
  "dropped": {
    "heart_rate": 0,
    "accelerometer": 0,
    "ibi": 0,
    "temperature": 0,
    "expired_batches": 0
  }
}
```

Schema validation rejects strings masquerading as numeric values, non-finite
numbers, future callback times relative to batch creation, out-of-order callbacks,
unequal axis lengths, unknown source/device fields and oversized bodies. IBI
artifacts are accepted into the raw dataset and filtered only for derived RMSSD.
Server reception epoch seconds are independent of watch time. Raw journal data
and the timing columns support later explicit alignment to video session clocks.
