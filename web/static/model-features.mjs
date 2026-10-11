// Live RGB transfer of the original causal event schema. Geometry is a proxy
// for the training Dlib points; its webcam accuracy has not been established.
export const CHANNELS = ['left_eye_openness','right_eye_openness','eye_closed_fraction',
  'long_closure_fraction','closure_age_seconds','long_closure_count','blink_count',
  'blink_duration_sum_seconds','blink_duration_max_seconds','mouth_ratio','mouth_open_fraction',
  'mouth_age_seconds','mouth_event_count','mouth_duration_sum_seconds','valid_fraction'];

export function meshRatios(points, width, height) {
  if (!points?.length || !width || !height) return null;
  const distance = (i,j) => Math.hypot((points[i].x-points[j].x)*width,(points[i].y-points[j].y)*height);
  const ear = p => (distance(p[1],p[5])+distance(p[2],p[4]))/(2*distance(p[0],p[3]));
  const left = ear([33,160,158,133,153,144]), right = ear([362,385,387,263,373,380]);
  const mouth = (distance(81,178)+distance(13,14)+distance(311,402))/(3*distance(78,308));
  return [left,right,mouth].every(Number.isFinite) && left>0.02 && right>0.02 && left<1 && right<1 && mouth>=0 && mouth<=2 ? [left,right,mouth] : null;
}

const quantile = (values,q) => {
  const sorted = [...values].sort((a,b)=>a-b), i=(sorted.length-1)*q, low=Math.floor(i);
  return sorted[low]+(sorted[Math.ceil(i)]-sorted[low])*(i-low);
};

export class LiveModelFeatures {
  constructor() { this.reset(); }
  reset() {
    this.origin=null; this.previous=null; this.reference=null; this.calibration=[]; this.baselineReference=null;
    this.mouthOn=0.6; this.mouthOff=0.45;
    this.seconds=new Map(); this.blinkTimes=[]; this.eyeStart=null; this.mouthStart=null;
    this.eyeCensored=this.mouthCensored=true; this.lastWindow=-1;
  }
  bucket(second) {
    if (!this.seconds.has(second)) this.seconds.set(second,{row:Array(15).fill(0),valid:0});
    return this.seconds.get(second);
  }
  push(timestamp,ratios) {
    if (this.origin===null) this.origin=Math.floor(timestamp/1000)*1000;
    const t=(timestamp-this.origin)/1000;
    if (this.previous && t<=this.previous.t) return;
    // Count only bounded observed time; long gaps are never filled/interpolated.
    if (this.previous?.ratios && this.previous.row) {
      const until=Math.min(t,this.previous.t+0.15);
      for(let a=this.previous.t;a<until-1e-9;) {
        const sec=Math.floor(a), b=Math.min(until,sec+1), dt=b-a, bucket=this.bucket(sec);
        for(const j of [0,1,2,3,9,10]) bucket.row[j]+=this.previous.row[j]*dt;
        bucket.valid+=dt; a=b;
      }
    }
    const gap=this.previous && t-this.previous.t>0.15;
    if (!ratios || gap) {
      this.eyeStart=this.mouthStart=null;
      this.eyeCensored=this.mouthCensored=true;
    }
    if (t<15) { if(ratios)this.calibration.push({t,ratios}); }
    else if (!this.reference) {
      const covered=this.calibration.reduce((sum,x,i,rows)=>sum+(i ? Math.min(0.15,x.t-rows[i-1].t):0),0);
      if(covered<12) { this.reset(); this.origin=Math.floor(timestamp/1000)*1000; return; }
      this.reference=[0,1].map(j=>quantile(this.calibration.map(x=>x.ratios[j]),0.9));
      if(this.reference.some(x=>x<0.1)) { this.reset(); this.origin=Math.floor(timestamp/1000)*1000; return; }
      // Freeze the user's first 15 seconds as their neutral reference.
      this.baselineReference=Array(15).fill(0);
      this.baselineReference[0]=this.calibration.reduce((s,x)=>s+Math.min(2,x.ratios[0]/this.reference[0]),0)/this.calibration.length;
      this.baselineReference[1]=this.calibration.reduce((s,x)=>s+Math.min(2,x.ratios[1]/this.reference[1]),0)/this.calibration.length;
      this.baselineReference[9]=this.calibration.reduce((s,x)=>s+x.ratios[2],0)/this.calibration.length;
      this.baselineReference[14]=1;
      // Normal baseline blinks are tolerated, and an already open mouth must
      // open further before it can become a new sustained mouth event.
      const mouthNeutral=quantile(this.calibration.map(x=>x.ratios[2]),0.9);
      this.mouthOn=Math.max(0.6,mouthNeutral+0.2);
      this.mouthOff=Math.max(0.45,mouthNeutral+0.1);
      let eyeStart=null,closed=0,long=0;
      for(let i=1;i<this.calibration.length;i++) {
        const p=this.calibration[i-1],x=this.calibration[i],dt=x.t-p.t;
        if(dt>0.15)eyeStart=null;
        const low=Math.max(...x.ratios.slice(0,2).map((v,j)=>v/this.reference[j]))<0.65;
        if(low) {
          if(eyeStart===null)eyeStart=x.t;
          closed+=Math.min(dt,0.15);
          if(x.t-eyeStart>0.8)long+=Math.min(dt,0.15);
        } else eyeStart=null;
      }
      this.baselineReference[2]=closed/covered;
      this.baselineReference[3]=long/covered;
    }
    let row=null;
    if (ratios && this.reference) {
      const [left,right]=ratios.slice(0,2).map((x,j)=>Math.min(2,x/this.reference[j]));
      const mouth=ratios[2]; row=Array(15).fill(0);
      row[0]=left; row[1]=right; row[9]=mouth; row[14]=1;
      if(this.eyeStart===null) {
        if(Math.max(left,right)<0.65)this.eyeStart=t;
        else if(Math.min(left,right)>0.75)this.eyeCensored=false;
      } else if(Math.min(left,right)>0.75) {
        const duration=t-this.eyeStart;
        if(!this.eyeCensored && duration>=0.08 && duration<=0.8) {
          row[6]=1; row[7]=row[8]=duration; this.blinkTimes.push(t);
        }
        this.eyeStart=null; this.eyeCensored=false;
      }
      if(this.eyeStart!==null) {
        const age=t-this.eyeStart; row[2]=1; row[3]=age>0.8 ? 1:0; row[4]=Math.min(60,age);
        if(!this.eyeCensored && age>0.8 && this.previous?.row?.[3]!==1)row[5]=1;
      }
      if(this.mouthStart===null) {
        if(mouth>this.mouthOn)this.mouthStart=t;
        else if(mouth<this.mouthOff)this.mouthCensored=false;
      } else if(mouth<this.mouthOff) {
        const duration=t-this.mouthStart;
        if(!this.mouthCensored && duration>=1) { row[12]=1; row[13]=duration; }
        this.mouthStart=null; this.mouthCensored=false;
      }
      if(this.mouthStart!==null) { row[10]=1; row[11]=Math.min(60,t-this.mouthStart); }
      const bucket=this.bucket(Math.floor(t));
      for(const j of [4,8,11])bucket.row[j]=Math.max(bucket.row[j],row[j]);
      for(const j of [5,6,7,12,13])bucket.row[j]+=row[j];
    }
    this.previous={t,ratios,row};
    for(const sec of this.seconds.keys())if(sec<t-125)this.seconds.delete(sec);
    this.blinkTimes=this.blinkTimes.filter(x=>x>=t-125);
  }
  window(timestamp) {
    if(this.origin===null || !this.reference)return {status:'Calibrating neutral baseline · first 15 seconds'};
    const end=Math.floor(timestamp/5000)*5-this.origin/1000, start=end-60;
    if(end-this.lastWindow<5)return null;
    const rows=[];
    for(let sec=start;sec<end;sec++) {
      const bucket=this.seconds.get(sec), coverage=Math.min(1,bucket?.valid||0), row=bucket?[...bucket.row]:Array(15).fill(0);
      for(const j of [0,1,2,3,9,10])row[j]=coverage?row[j]/bucket.valid:0;
      row[14]=coverage; rows.push(row);
    }
    const weights=rows.map(x=>x[14]), observed=weights.reduce((a,b)=>a+b,0);
    // The live demo may use a partial window. The validity channel explicitly
    // preserves gaps; no geometry, closures or events are filled into them.
    if(observed<10)return {status:`Collecting visible face · ${observed.toFixed(1)}/10 observed seconds`};
    if(weights.slice(-5).reduce((a,b)=>a+b,0)<0.5)return {status:'Waiting for a recent face observation · last score retained'};
    this.lastWindow=end;
    const sum=j=>rows.reduce((a,x)=>a+x[j],0), max=j=>Math.max(...rows.map(x=>x[j]));
    const mean=j=>rows.reduce((a,x)=>a+x[j]*x[14],0)/observed;
    const std=j=>Math.sqrt(rows.reduce((a,x)=>a+(x[j]-mean(j))**2*x[14],0)/observed);
    const trend=j=>{
      const avg=part=>{
        const count=part.reduce((a,x)=>a+x[14],0);
        return count ? part.reduce((a,x)=>a+x[j]*x[14],0)/count : null;
      };
      if(avg(rows.slice(30))===null || avg(rows.slice(0,30))===null)return 0;
      return avg(rows.slice(30))-avg(rows.slice(0,30));
    };
    const blinks=this.blinkTimes.filter(x=>x>=start&&x<end);
    const values=[mean(0),std(0),mean(1),std(1),rows.reduce((a,x)=>a+Math.abs(x[0]-x[1])*x[14],0)/observed,
      mean(2),mean(3),max(4),sum(5)/observed*60,sum(6)/observed*60,sum(6)?sum(7)/sum(6):0,max(8),
      blinks.length>1?(blinks.at(-1)-blinks[0])/(blinks.length-1):0,mean(9),std(9),mean(10),max(11),
      sum(12)/observed*60,sum(12)?sum(13)/sum(12):0,observed/60,trend(2),trend(10)];
    const names=['left_eye_mean','left_eye_variability','right_eye_mean','right_eye_variability','eye_asymmetry_mean',
      'eye_closed_fraction','long_closure_fraction','longest_closure_seconds','long_closures_per_minute',
      'blinks_per_minute','blink_duration_mean_seconds','blink_duration_max_seconds','interblink_interval_mean_seconds',
      'mouth_ratio_mean','mouth_ratio_variability','mouth_open_fraction','longest_mouth_open_seconds',
      'mouth_events_per_minute','mouth_event_duration_mean_seconds','valid_frame_fraction','eye_closure_trend','mouth_open_trend'];
    return {sequence:CHANNELS.map((_,j)=>rows.map(x=>x[j])),channels:CHANNELS,
      features:Object.fromEntries(names.map((name,i)=>[name,values[i]])),
      observedSeconds:observed, partial:observed<54 || Math.min(...weights)<0.5,
      baselineReference:[...this.baselineReference],
      trendsAvailable:weights.slice(0,30).some(x=>x>0)&&weights.slice(30).some(x=>x>0),
      startRelativeMs:this.origin+start*1000,endRelativeMs:this.origin+end*1000};
  }
}
