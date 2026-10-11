"""Garmin-to-UL-DD demo transfer using real samples and explicit approximations.

Temperature is last-observation-carried-forward, as requested. No HR-to-IBI
conversion is made. Motion is scaled mg -> E4 raw 1/64-g counts. Sampling rate,
callback-bin IBI times and the temperature source differ from training; this is
an experimental device transfer, not established input parity or calibration.
"""
from collections import defaultdict, deque
import math

import numpy as np
import pandas as pd

from src.features.watch_features import _extract_window_features


class GarminWindow:
    def __init__(self):
        self.session = None
        self.rows = deque(maxlen=5000)
        self.seen = {}
        self.temperature = None
        self.temperature_at = None
        self.last_end = None
        self.epoch_offset = None
        self.quality = {'missing':['60-second sensor window','first temperature','genuine IBI']}

    def reset(self, session):
        self.__init__()
        self.session = session

    def ingest(self, packet):
        if self.session != packet.session: self.reset(packet.session)
        if self.seen.get('uptime',-1)>packet.watchUptimeMs:
            raise ValueError('Watch uptime reset requires a new session')
        self.seen['uptime']=packet.watchUptimeMs
        now = packet.watchUptimeMs
        # First packet anchors uptime to watch UTC (one-second resolution).
        # Both modalities use UTC seconds and five-second window boundaries.
        if self.epoch_offset is None:
            self.epoch_offset = round(packet.sentAt*1000)-now
        if abs(round(packet.sentAt*1000)-(now+self.epoch_offset))>2000:
            raise ValueError("Watch clock changed; start a new session")
        # A non-null Sensor.Info value may still be the same callback. Preserve
        # its original timestamp; carried readings must not acquire a new age.
        if packet.temperatureC is not None and math.isfinite(packet.temperatureC):
            if self.temperature_at is None or (packet.temperatureAtMs is not None and packet.temperatureAtMs > self.temperature_at):
                self.temperature, self.temperature_at = packet.temperatureC, packet.temperatureAtMs
        stamp = packet.heartRateAtMs
        if (stamp is not None and packet.heartRateBpm is not None and 0 < packet.heartRateBpm <= 250 and
            0 <= now-stamp <= 3000 and self.seen.get('hr') != stamp):
            self.rows.append((stamp,'hr',packet.heartRateBpm))
            self.seen['hr'] = stamp
        if self.seen.get('batch') != packet.batchId:
            self.seen['batch'] = packet.batchId
            callback = packet.batchReceivedAtMs
            if callback is not None and 0 <= now-callback <= 3000:
                intervals = packet.beatIntervalsMs or []
                for value in intervals:
                    if value is not None and 300 <= value <= 2000:
                        self.rows.append((callback,'ibi',value/1000))
                axes = packet.accelerometer
                if axes and not axes.truncated and axes.sampleRateHz and len(axes.x) >= axes.sampleRateHz*0.8:
                    stamps = axes.sensorTimestampMs
                    valid_stamps = [t for t in stamps if t is not None]
                    if len(valid_stamps) == len(stamps) and valid_stamps and all(b>a for a,b in zip(stamps,stamps[1:])):
                        last = stamps[-1]
                        for index, sensor_time in enumerate(stamps):
                            values = [axes.x[index],axes.y[index],axes.z[index]]
                            # Anchor relative motion timestamps to callback uptime.
                            # This does not claim the original sensor clock is UTC.
                            at = callback-(last-sensor_time)
                            if (last-sensor_time <= 1500 and all(x is not None for x in values) and
                                sensor_time > self.seen.get('motion_stamp',-1)):
                                self.rows.append((at,'acc',tuple(float(x)*64/1000 for x in values)))
                        self.seen['motion_stamp'] = last
        # A separate 1-Hz temperature trace records the carried value, even when
        # the latest packet explicitly contained null. Never fabricate the first.
        second = now//1000
        if self.seen.get('temp_second') != second:
            self.rows.append((second*1000,'temp',self.temperature))
            self.seen['temp_second'] = second
        # Bounded by time and size; 25-Hz acceleration needs >60*25 observations.
        while self.rows and self.rows[0][0] < now-120_000: self.rows.popleft()
        end_second = (now+self.epoch_offset)//5000*5
        start_second = end_second-60
        grouped = defaultdict(lambda:defaultdict(list))
        for at,kind,value in self.rows:
            sec = (at+self.epoch_offset)//1000
            if start_second-5 <= sec < end_second: grouped[sec][kind].append(value)
        records = []
        for sec in range(start_second-5,end_second):
            values = grouped[sec]
            acc = np.array(values['acc']) if values['acc'] else np.empty((0,3))
            variance = np.var(acc,axis=0) if len(acc)>=20 else [np.nan]*3
            temps = [x for x in values['temp'] if x is not None]
            records.append({'heart_rate':np.mean(values['hr']) if values['hr'] else np.nan,
                'motion_source_second':sec if len(acc)>=20 else np.nan,
                'temp':temps[-1] if temps else np.nan,
                'ibi_mean':np.mean(values['ibi']) if values['ibi'] else np.nan,
                'ibi_count':len(values['ibi']),
                **dict(zip(['accel_var_x','accel_var_y','accel_var_z'],variance))})
        table = pd.DataFrame(records)
        # Forward fill across dropped packets, without ever backfilling a value
        # measured after the time being predicted.
        table['temp'] = table['temp'].ffill()
        # Carry the last measured per-second variance over brief transport gaps.
        # No raw accelerometer samples or timestamps are invented.
        raw_motion=table.accel_var_x.notna().iloc[-60:]
        raw_hr=table.heart_rate.notna().iloc[-60:]
        table['heart_rate']=table.heart_rate.ffill(limit=3)
        for name in ['accel_var_x','accel_var_y','accel_var_z','motion_source_second']:
            table[name]=table[name].ffill(limit=5)
        table=table.iloc[-60:].reset_index(drop=True)
        motion_age=(np.arange(start_second,end_second)-table.motion_source_second)*1000
        coverage = {'hr':float(table.heart_rate.notna().mean()),
                    'hr_observed':float(raw_hr.mean()),
                    'motion':float(table.accel_var_x.notna().mean()),
                    'motion_observed':float(raw_motion.mean()),
                    'temperature':float(table.temp.notna().mean()),
                    'ibi_seconds':int((table.ibi_count>0).sum())}
        missing = []
        if len(self.rows)==0 or not any(at+self.epoch_offset<=start_second*1000+1000 for at,_,_ in self.rows):
            missing.append('full 60-second window')
        if coverage['hr'] < 0.9: missing.append('heart rate coverage')
        if coverage['motion'] < 0.9: missing.append('timestamped accelerometer coverage')
        if coverage['temperature'] < 0.9: missing.append('first temperature / carried history')
        if coverage['ibi_seconds'] < 2: missing.append('genuine beat intervals')
        self.quality = {'coverage':coverage,'missing':missing,'temperature_c':self.temperature,
            'hr_carried_seconds':int((table.heart_rate.notna().to_numpy() & ~raw_hr.to_numpy()).sum()),
            'hr_carry_limit_ms':3000,
            'motion_carried_seconds':int((table.accel_var_x.notna().to_numpy() & ~raw_motion.to_numpy()).sum()),
            'motion_max_age_ms':int(motion_age.max()) if motion_age.notna().any() else None,
            'motion_carry_limit_ms':5000,
            'temperature_age_ms':None if self.temperature_at is None else now-self.temperature_at,
            'temperature_carried':packet.temperatureC is None and self.temperature is not None,
            'transfer':'experimental_garmin_to_uldd', 'acceleration_scale':0.064,
            'timing':'callback-anchored; first-packet UTC resolution one second; five-second UTC boundaries',
            'temperature_source':'Sensor.Info; not established as skin temperature',
            'ibi_timing':'per-second callback-bin means; actual beat times unavailable'}
        if missing or (self.last_end is not None and end_second-self.last_end<5): return None
        features = _extract_window_features(table)
        if not all(math.isfinite(v) for v in features.values()): return None
        self.last_end = end_second
        end_epoch = end_second*1000
        return {'features':features,'schema_id':'watch.garmin.transfer.v1',
                'window':{'start_ms':end_epoch-60_000,'end_ms':end_epoch}}
