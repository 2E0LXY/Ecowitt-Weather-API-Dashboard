import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const Icon = ({ name, className = 'w-5 h-5' }) => {
  const paths = {
    activity: <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
    pin: <><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></>,
    play: <polygon points="5 3 19 12 5 21 5 3" />,
    pause: <><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></>,
    layers: <><polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" /></>,
    chart: <><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></>,
    alert: <><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
    sun: <><circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /><line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" /><line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" /></>,
    moon: <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />,
    cloud: <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z" />,
    rain: <><path d="M16 13v8" /><path d="M8 13v8" /><path d="M12 15v8" /><path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25" /></>,
    wind: <><path d="M9.59 4.59A2 2 0 1 1 11 8H2" /><path d="M12.59 19.41A2 2 0 1 0 14 16H2" /><path d="M17.73 7.73A2.5 2.5 0 1 1 19.5 12H2" /></>,
    umbrella: <><path d="M22 12a10.06 10.06 0 0 0-20 0Z" /><path d="M12 12v8a2 2 0 0 0 4 0" /><path d="M12 2v1" /></>,
    gauge: <><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /><path d="M12 12 8 8" /><path d="M3.34 16A10 10 0 1 1 20.66 16" /></>,
    info: <><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></>,
    shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></>,
    compass: <><circle cx="12" cy="12" r="10" /><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" /></>,
    clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
    radio: <><circle cx="12" cy="12" r="2" /><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14" /></>,
  };
  return <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>{paths[name] || paths.activity}</svg>;
};

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '', stack: '' };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error) };
  }
  componentDidCatch(_error, info) {
    this.setState({ stack: info.componentStack || '' });
  }
  render() {
    if (!this.state.hasError) return this.props.children;
    return <div className="min-h-screen bg-red-950 text-white p-6 font-mono"><Icon name="alert" className="w-10 h-10 text-red-400 mb-4" /><h1 className="text-2xl font-bold text-red-300">WeatherNext failed to render</h1><p className="mt-3 rounded-lg bg-red-900/50 p-3">{this.state.message}</p><pre className="mt-3 overflow-auto whitespace-pre-wrap text-[10px] text-red-200">{this.state.stack}</pre></div>;
  }
}

const LOCATIONS = [
  { id: 'tingley', name: 'Tingley, Wakefield', country: 'UK', lat: 53.7314, lon: -1.5621, elevation: 135, tzOffset: 1, climate: 'Temperate Maritime', baseTemp: 16.4, basePress: 1012.8, baseWind: 21.0, basePrecip: 0.8 },
  { id: 'sheffield', name: 'Sheffield', country: 'UK', lat: 53.3811, lon: -1.4701, elevation: 85, tzOffset: 1, climate: 'Temperate Oceanic', baseTemp: 17.1, basePress: 1013.4, baseWind: 19.5, basePrecip: 0.6 },
  { id: 'hisaronu', name: 'Hisarönü, Dalaman', country: 'Turkey', lat: 36.5786, lon: 29.1482, elevation: 420, tzOffset: 3, climate: 'Mediterranean Mountain', baseTemp: 31.6, basePress: 1009.2, baseWind: 13.8, basePrecip: 0.0 },
  { id: 'playa_ingles', name: 'Playa del Inglés', country: 'Spain', lat: 27.7594, lon: -15.5719, elevation: 18, tzOffset: 1, climate: 'Subtropical Oceanic', baseTemp: 26.8, basePress: 1016.4, baseWind: 24.2, basePrecip: 0.1 },
];

const VARIABLE_CONFIG = {
  temp: { label: '2m Temp', unit: '°C' },
  wind: { label: '10m Wind', unit: 'km/h' },
  precip: { label: 'Precipitation', unit: 'mm/h' },
  mslp: { label: 'Pressure', unit: 'hPa' },
};

const coord = (value, positive, negative) => `${Math.abs(value).toFixed(3)}°${value >= 0 ? positive : negative}`;

function WeatherNextApp() {
  const [selectedLoc, setSelectedLoc] = useState(LOCATIONS[0]);
  const [activeTab, setActiveTab] = useState('summary');
  const [leadStep, setLeadStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [activeVar, setActiveVar] = useState('temp');
  const [initTimestamp] = useState(() => Date.now());
  const [inspectedPoint, setInspectedPoint] = useState({ x: 0.5, y: 0.5, lat: LOCATIONS[0].lat, lon: LOCATIONS[0].lon, val: LOCATIONS[0].baseTemp });

  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const interactingRef = useRef(false);
  const activeVarRef = useRef(activeVar);
  const leadStepRef = useRef(leadStep);
  const probeRef = useRef(inspectedPoint);

  useEffect(() => { activeVarRef.current = activeVar; }, [activeVar]);
  useEffect(() => { leadStepRef.current = leadStep; }, [leadStep]);
  useEffect(() => { probeRef.current = inspectedPoint; }, [inspectedPoint]);

  useEffect(() => {
    if (!isPlaying) return undefined;
    const id = window.setInterval(() => setLeadStep((step) => (step + 1) % 17), 1000);
    return () => window.clearInterval(id);
  }, [isPlaying]);

  const ensemble = useMemo(() => {
    const steps = 17;
    const count = 64;
    const members = [];
    const timestamps = [];
    const latRad = selectedLoc.lat * Math.PI / 180;
    const lonRad = selectedLoc.lon * Math.PI / 180;
    const seed = Math.abs(Math.sin(latRad * 7.1 + lonRad * 3.3) * 100);
    const utcHour = new Date(initTimestamp).getUTCHours();
    const baseHour = (utcHour + selectedLoc.tzOffset + 24) % 24;

    for (let s = 0; s < steps; s += 1) {
      const totalHour = baseHour + s * 3;
      const hour = totalHour % 24;
      const day = Math.floor(totalHour / 24);
      timestamps.push({ hour, timeStr: `${String(Math.floor(hour)).padStart(2, '0')}:00`, dateStr: day === 0 ? 'Today' : day === 1 ? 'Tomorrow' : `Day +${day}` });
    }

    for (let m = 0; m < count; m += 1) {
      const trace = [];
      const memberPhase = ((m - 32) / 32) * 2.1;
      const perturb = Math.sin(seed + m * 0.73) * 0.9;
      for (let s = 0; s < steps; s += 1) {
        const hour = baseHour + s * 3;
        const solar = Math.sin(((hour - 8) / 24) * Math.PI * 2);
        const diurnal = solar * (selectedLoc.elevation > 300 ? 5.2 : 3.8);
        const synoptic = Math.cos(s * 0.35 + lonRad * 2) * 1.6;
        const spread = (s / steps) * (memberPhase * 1.5 + perturb);
        trace.push(Number((selectedLoc.baseTemp + diurnal + synoptic + spread).toFixed(1)));
      }
      members.push(trace);
    }

    const mean = [], p10 = [], p90 = [], spread = [], rainProbs = [];
    for (let s = 0; s < steps; s += 1) {
      const slice = members.map((member) => member[s]).sort((a, b) => a - b);
      mean.push(Number((slice.reduce((a, b) => a + b, 0) / count).toFixed(1)));
      p10.push(slice[Math.floor(count * 0.1)]);
      p90.push(slice[Math.floor(count * 0.9)]);
      spread.push(Number((slice[slice.length - 1] - slice[0]).toFixed(1)));
      let wet = 0;
      for (let m = 0; m < count; m += 1) {
        const moisture = Math.sin(s * 0.42 + seed + m * 0.1);
        if ((selectedLoc.basePrecip > 0.4 && moisture > 0.15) || (selectedLoc.basePrecip <= 0.2 && moisture > 0.65)) wet += 1;
      }
      rainProbs.push(Math.round((wet / count) * 100));
    }
    return { timestamps, members, mean, p10, p90, spread, rainProbs };
  }, [selectedLoc, initTimestamp]);

  const safeLead = Math.min(Math.max(leadStep, 0), 16);
  const leadHours = safeLead * 3;
  const currentTemp = ensemble.mean[safeLead] ?? selectedLoc.baseTemp;
  const currentP10 = ensemble.p10[safeLead] ?? currentTemp - 2;
  const currentP90 = ensemble.p90[safeLead] ?? currentTemp + 2;
  const currentSpread = ensemble.spread[safeLead] ?? 4;
  const currentRain = ensemble.rainProbs[safeLead] ?? 0;
  const currentWind = Number((selectedLoc.baseWind + Math.sin(safeLead * 0.48 + selectedLoc.lat * 0.1) * 4.8).toFixed(1));
  const currentPressure = Number((selectedLoc.basePress + Math.cos(safeLead * 0.32 + selectedLoc.lon * 0.05) * 3.2).toFixed(1));
  const timeInfo = ensemble.timestamps[safeLead] || { hour: 12, timeStr: '12:00', dateStr: 'Today' };
  const isNight = timeInfo.hour < 6 || timeInfo.hour >= 21;

  const summary = useMemo(() => {
    let icon = isNight ? 'moon' : 'sun';
    let headline = isNight ? 'Clear Night Sky' : 'Crisp & Pleasant';
    let text = `Stable pressure field maintains ${currentTemp}°C with balanced atmospheric ventilation.`;
    let guidance = isNight ? 'A light jacket or warm layer may be useful.' : 'Comfortable daytime clothing is suitable for outdoor activity.';
    let viability = 'Ideal conditions for outdoor activity';
    if (currentRain > 55) {
      icon = 'rain'; headline = isNight ? 'Overnight Precipitation' : 'Showers Expected';
      text = `The local ensemble indicates a ${currentRain}% simulated rain likelihood around +${leadHours}h.`;
      guidance = 'A waterproof outer layer or umbrella is advisable.';
      viability = 'Fair — plan around passing showers';
    } else if (currentRain > 25) {
      icon = 'cloud'; headline = 'Scattered Cloud Cover';
      text = `Partly cloudy conditions with a simulated rain risk of ${currentRain}%.`;
      guidance = 'Light layers are suitable; keep an outer shell available.';
      viability = 'Good for normal outdoor routines';
    } else if (currentTemp > 28) {
      icon = isNight ? 'moon' : 'sun'; headline = isNight ? 'Warm Night' : 'Hot & Bright';
      text = `Temperatures are simulated around ${currentTemp}°C at this forecast step.`;
      guidance = 'Use sun protection and drink regularly in warm conditions.';
      viability = 'Best in cooler morning or evening periods';
    }
    const alert = currentWind > 34 ? `Strong-wind signal: simulated gusts may reach about ${Math.round(currentWind * 1.38)} km/h.` : null;
    const outlook = [{ label: 'Today', step: 1 }, { label: 'Tomorrow', step: 8 }, { label: 'Day 3', step: 15 }].map(({ label, step }) => ({
      day: label,
      high: Math.round(ensemble.p90[step] ?? selectedLoc.baseTemp + 2),
      low: Math.round(ensemble.p10[step] ?? selectedLoc.baseTemp - 2),
      cond: (ensemble.rainProbs[step] ?? 0) > 50 ? 'Showers' : 'Clear',
    }));
    return { icon, headline, text, guidance, viability, alert, outlook };
  }, [isNight, currentTemp, currentRain, currentWind, leadHours, ensemble, selectedLoc.baseTemp]);

  const changeLocation = useCallback((loc) => {
    setSelectedLoc(loc);
    setLeadStep(0);
    const probe = { x: 0.5, y: 0.5, lat: loc.lat, lon: loc.lon, val: loc.baseTemp };
    setInspectedPoint(probe);
    probeRef.current = probe;
  }, []);

  useEffect(() => {
    if (activeTab !== 'synoptic') return undefined;
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    let mounted = true;
    const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    let width = 320;
    let height = 300;

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      width = Math.max(280, Math.floor(rect?.width || 800));
      height = Math.max(240, Math.floor(rect?.height || 450));
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const particles = Array.from({ length: 260 }, () => ({ x: Math.random() * width, y: Math.random() * height, age: Math.random() * 60, maxAge: 40 + Math.random() * 40, speed: 1 + Math.random() * 1.5 }));
    let time = 0;
    const render = () => {
      if (!mounted) return;
      time += 0.035;
      const variable = activeVarRef.current;
      const lead = leadStepRef.current;
      const probe = probeRef.current;
      ctx.fillStyle = 'rgba(5,9,20,0.35)';
      ctx.fillRect(0, 0, width, height);

      for (let x = 0; x < width; x += 40) {
        for (let y = 0; y < height; y += 40) {
          const nx = x / width;
          const ny = y / height;
          const v = Math.max(0, Math.min(1, (Math.sin(nx * 3.2 + lead * 0.12) * Math.cos(ny * 2.6) + 1) / 2));
          ctx.fillStyle = variable === 'temp' ? `rgba(${Math.floor(v * 220)},${Math.floor(100 + (1 - v) * 70)},180,.08)` : variable === 'precip' ? `rgba(14,165,233,${v * .2})` : variable === 'wind' ? `rgba(16,185,129,${v * .12})` : `rgba(139,92,246,${v * .12})`;
          ctx.fillRect(x, y, 40, 40);
        }
      }

      ctx.lineWidth = 1.3;
      particles.forEach((p) => {
        const nx = p.x / width;
        const ny = p.y / height;
        const u = 1.8 + Math.sin(ny * 3.8 + time * 0.08) * 1.2;
        const v = Math.sin(nx * 3.2 + time * 0.06) * (selectedLoc.lat / 90) * 1.2;
        ctx.beginPath(); ctx.moveTo(p.x, p.y);
        p.x += u * p.speed; p.y += v * p.speed; p.age += 1;
        ctx.lineTo(p.x, p.y);
        const alpha = Math.max(0, Math.sin((p.age / p.maxAge) * Math.PI) * 0.75);
        ctx.strokeStyle = variable === 'wind' ? `rgba(52,211,153,${alpha})` : `rgba(56,189,248,${alpha})`;
        ctx.stroke();
        if (p.age >= p.maxAge || p.x > width || p.y > height || p.x < 0 || p.y < 0) {
          p.x = Math.random() * width; p.y = Math.random() * height; p.age = 0; p.maxAge = 40 + Math.random() * 40;
        }
      });

      const cx = probe.x * width, cy = probe.y * height;
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(cx, cy, 12, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx - 18, cy); ctx.lineTo(cx + 18, cy); ctx.moveTo(cx, cy - 18); ctx.lineTo(cx, cy + 18); ctx.stroke();
      rafRef.current = requestAnimationFrame(render);
    };

    window.addEventListener('resize', resize, { passive: true });
    rafRef.current = requestAnimationFrame(render);
    return () => {
      mounted = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resize);
    };
  }, [activeTab, selectedLoc]);

  const updateProbe = useCallback((clientX, clientY) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    const probe = {
      x, y,
      lat: Number((selectedLoc.lat + (0.5 - y) * 3.5).toFixed(3)),
      lon: Number((selectedLoc.lon + (x - 0.5) * 5).toFixed(3)),
      val: Number((currentTemp + Math.sin(x * Math.PI) * Math.cos(y * Math.PI) * 1.8).toFixed(1)),
    };
    setInspectedPoint(probe);
    probeRef.current = probe;
  }, [selectedLoc, currentTemp]);

  const pointerDown = useCallback((e) => {
    interactingRef.current = true;
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* ignored */ }
    updateProbe(e.clientX, e.clientY);
  }, [updateProbe]);
  const pointerMove = useCallback((e) => { if (interactingRef.current) updateProbe(e.clientX, e.clientY); }, [updateProbe]);
  const pointerUp = useCallback((e) => {
    interactingRef.current = false;
    try { e.currentTarget.releasePointerCapture?.(e.pointerId); } catch { /* ignored */ }
  }, []);

  const probeValue = activeVar === 'temp' ? inspectedPoint.val : activeVar === 'wind' ? currentWind : activeVar === 'precip' ? Number(((currentRain / 100) * Math.max(0.1, selectedLoc.basePrecip * 3)).toFixed(1)) : currentPressure;

  return <div className="min-h-screen w-full overflow-x-hidden bg-[#050914] text-slate-100 selection:bg-cyan-500/30">
    <header className="border-b border-slate-800/80 bg-[#081021]/95 px-4 py-3.5 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl border border-cyan-400/40 bg-gradient-to-tr from-cyan-600 to-indigo-700"><Icon name="radio" className="h-5 w-5 text-white" /></div><div><h1 className="flex items-center gap-2 text-base font-extrabold text-white">WeatherNext 3 <span className="rounded-full border border-cyan-800 bg-cyan-950/90 px-2 py-0.5 text-[10px] font-bold text-cyan-400">LOCAL CORE</span></h1><p className="text-xs text-slate-400">64-member local forecast visualiser</p></div></div>
        <div className="flex w-full gap-2 overflow-x-auto pb-1 sm:w-auto sm:pb-0">{LOCATIONS.map((loc) => <button key={loc.id} onClick={() => changeLocation(loc)} className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold ${selectedLoc.id === loc.id ? 'bg-cyan-600 text-white' : 'border border-slate-800 bg-slate-900 text-slate-400'}`}><Icon name="pin" className="h-3 w-3 text-cyan-300" />{loc.name.split(',')[0]}</button>)}</div>
      </div>
    </header>

    <div className="border-b border-slate-800/80 bg-[#081226] px-4 py-2.5 lg:px-8"><div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="flex w-full gap-1.5 overflow-x-auto pb-1 md:w-auto md:pb-0">{[{ id: 'summary', label: 'Summary', icon: 'info' }, { id: 'synoptic', label: 'Streamlines', icon: 'layers' }, { id: 'dispersion', label: 'Ensemble', icon: 'chart' }].map((tab) => <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold ${activeTab === tab.id ? 'border-cyan-500/50 bg-cyan-500/20 text-cyan-300' : 'border-transparent text-slate-400'}`}><Icon name={tab.icon} className="h-3.5 w-3.5" />{tab.label}</button>)}</div>
      <div className="flex w-full items-center gap-3 text-xs md:w-auto"><button onClick={() => setIsPlaying((v) => !v)} className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-cyan-600 px-3 py-1.5 font-bold text-white md:flex-none"><Icon name={isPlaying ? 'pause' : 'play'} className="h-3.5 w-3.5" />{isPlaying ? 'Pause' : 'Animate'}</button><div className="flex items-center gap-2 whitespace-nowrap rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5"><Icon name="clock" className="h-3.5 w-3.5 text-cyan-400" /><span className="font-mono text-cyan-300">+{leadHours}h</span><span className="hidden font-mono text-[11px] text-slate-400 sm:inline">({timeInfo.dateStr} {timeInfo.timeStr})</span></div></div>
    </div></div>

    <main className="mx-auto w-full max-w-[1720px] flex-1 space-y-6 p-4 lg:p-8">
      {activeTab === 'summary' && <div className="space-y-6">
        <section className="relative overflow-hidden rounded-3xl border border-cyan-900/40 bg-[#091428] p-5 shadow-2xl lg:p-8"><div className="relative z-10 flex flex-col justify-between gap-6 lg:flex-row lg:items-center"><div className="space-y-3"><div className="inline-flex items-center gap-2 rounded-full border border-cyan-700/60 bg-cyan-950/80 px-3 py-1 text-xs text-cyan-300"><Icon name="pin" className="h-3.5 w-3.5" />{selectedLoc.name}, {selectedLoc.country}</div><h2 className="flex items-center gap-3 text-2xl font-black text-white lg:text-4xl">{summary.headline}<Icon name={summary.icon} className="h-8 w-8 text-cyan-400" /></h2><p className="text-sm leading-relaxed text-slate-300 lg:text-base">{summary.text}</p></div><div className="flex w-full flex-col items-center gap-4 rounded-2xl border border-slate-800 bg-slate-950/80 p-5 sm:flex-row sm:gap-6 lg:w-auto"><div className="text-center sm:text-left"><div className="flex items-start justify-center sm:justify-start"><span className="text-5xl font-extralight text-white lg:text-6xl">{Math.round(currentTemp)}</span><span className="ml-1 text-2xl font-light text-cyan-400">°C</span></div><div className="mt-1 text-xs font-mono text-slate-400">Range: {Math.round(currentP10)}° to {Math.round(currentP90)}°</div></div><div className="h-px w-full bg-slate-800 sm:h-14 sm:w-px" /><div className="w-full space-y-2 text-xs text-slate-300 sm:w-auto"><div className="flex items-center gap-2"><Icon name="umbrella" className="h-4 w-4 text-cyan-400" />Rain: {currentRain}%</div><div className="flex items-center gap-2"><Icon name="wind" className="h-4 w-4 text-emerald-400" />Wind: {currentWind} km/h</div><div className="flex items-center gap-2"><Icon name="gauge" className="h-4 w-4 text-purple-400" />MSLP: {currentPressure} hPa</div></div></div></div>{summary.alert && <div className="mt-4 flex items-center gap-2 rounded-xl bg-amber-950/40 p-3 text-xs text-amber-300"><Icon name="alert" className="h-4 w-4 shrink-0 text-amber-400" />{summary.alert}</div>}</section>
        <section className="grid grid-cols-1 gap-4 md:grid-cols-3 lg:gap-6"><div className="rounded-2xl border border-slate-800 bg-[#0a1224] p-5"><div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase text-cyan-400"><Icon name="shield" className="h-4 w-4" />Guidance</div><p className="text-xs leading-relaxed text-slate-300">{summary.guidance}</p><div className="mt-3 border-t border-slate-800 pt-2 text-[11px] text-slate-400">Viability: {summary.viability}</div></div><div className="rounded-2xl border border-slate-800 bg-[#0a1224] p-5"><div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase text-cyan-400"><Icon name="activity" className="h-4 w-4" />Certainty</div><p className="mb-3 text-xs text-slate-300">Model spread is ±{(currentSpread / 2).toFixed(1)}°C.</p><div className="h-2 w-full rounded-full border border-slate-800 bg-slate-950"><div className="h-full rounded-full bg-cyan-500" style={{ width: `${Math.max(20, Math.min(95, 100 - currentSpread * 9))}%` }} /></div></div><div className="rounded-2xl border border-slate-800 bg-[#0a1224] p-5"><div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase text-cyan-400"><Icon name="compass" className="h-4 w-4" />Location</div><p className="text-xs leading-relaxed text-slate-300">{selectedLoc.climate}. Elev: {selectedLoc.elevation}m.</p><div className="mt-3 border-t border-slate-800 pt-2 text-[11px] text-cyan-400">{coord(selectedLoc.lat, 'N', 'S')}, {coord(selectedLoc.lon, 'E', 'W')}</div></div></section>
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">{summary.outlook.map((d) => <div key={d.day} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900 p-4"><div><span className="block text-xs font-semibold text-cyan-400">{d.day}</span><span className="block text-sm font-bold text-white">{d.cond}</span></div><div className="text-right"><div className="text-xl font-bold text-white">{d.high}°</div><div className="text-xs text-slate-500">{d.low}°</div></div></div>)}</section>
      </div>}

      {activeTab === 'synoptic' && <section className="flex h-[500px] flex-col rounded-2xl border border-slate-800 bg-[#0a1224] p-4 lg:h-[600px] lg:p-5"><div className="mb-3 flex flex-col justify-between gap-3 border-b border-slate-800 pb-3 sm:flex-row sm:items-center"><h3 className="text-sm font-bold lg:text-base">Streamline Simulation</h3><div className="flex flex-wrap gap-1.5">{Object.entries(VARIABLE_CONFIG).map(([key, cfg]) => <button key={key} onClick={() => setActiveVar(key)} className={`rounded px-2 py-1 text-xs ${activeVar === key ? 'bg-cyan-600 text-white' : 'border border-slate-800 bg-slate-900'}`}>{cfg.label}</button>)}</div></div><div className="relative flex-1 overflow-hidden rounded-xl border border-slate-800 bg-[#050914]" style={{ touchAction: 'none' }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}><canvas ref={canvasRef} className="block h-full w-full" /><div className="pointer-events-none absolute left-3 top-3 rounded-xl border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs"><div className="mb-1 font-bold text-cyan-400">Probe Active</div><div>{coord(inspectedPoint.lat, 'N', 'S')}, {coord(inspectedPoint.lon, 'E', 'W')}</div><div>Val: <b className="text-white">{probeValue}{VARIABLE_CONFIG[activeVar].unit}</b></div></div></div></section>}

      {activeTab === 'dispersion' && <section className="flex h-[500px] flex-col rounded-2xl border border-slate-800 bg-[#0a1224] p-4 lg:h-[600px] lg:p-5"><h3 className="border-b border-slate-800 pb-3 text-sm font-bold lg:text-base">64-Member Probabilistic Fan</h3><div className="relative mt-4 min-h-[250px] w-full flex-1"><svg className="h-full w-full" viewBox="0 0 800 380" preserveAspectRatio="none"><defs><linearGradient id="fan" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#06b6d4" stopOpacity="0.25" /><stop offset="100%" stopColor="#06b6d4" stopOpacity="0.05" /></linearGradient></defs>{[0,95,190,285,380].map((y) => <line key={y} x1="0" y1={y} x2="800" y2={y} stroke="#1e293b" strokeDasharray="3 3" />)}{(() => { const all = [...ensemble.p10, ...ensemble.p90]; const min = Math.min(...all) - 2.5; const max = Math.max(...all) + 2.5; const range = Math.max(4, max - min); const steps = ensemble.timestamps.length - 1; const x = (i) => Math.round((i / steps) * 800); const y = (v) => Math.round(360 - ((v - min) / range) * 340); const upper = ensemble.p90.map((v,i) => `${x(i)},${y(v)}`); const lower = ensemble.p10.slice().reverse().map((v,i) => `${x(steps - i)},${y(v)}`); const fan = `M ${upper.join(' L ')} L ${lower.join(' L ')} Z`; const mean = ensemble.mean.map((v,i) => `${i === 0 ? 'M' : 'L'} ${x(i)},${y(v)}`).join(' '); return <><path d={fan} fill="url(#fan)" />{ensemble.members.slice(0,24).map((member,index) => <path key={index} d={member.map((v,i) => `${i === 0 ? 'M' : 'L'} ${x(i)},${y(v)}`).join(' ')} fill="none" stroke="#0284c7" strokeWidth="0.8" strokeOpacity="0.22" />)}<path d={mean} fill="none" stroke="#22d3ee" strokeWidth="3" strokeLinecap="round" /><line x1={x(safeLead)} y1="0" x2={x(safeLead)} y2="380" stroke="#f59e0b" strokeWidth="2" strokeDasharray="4 4" /><circle cx={x(safeLead)} cy={y(currentTemp)} r="5" fill="#f59e0b" /></>; })()}</svg></div><div className="mt-2 flex justify-between overflow-hidden font-mono text-[9px] text-slate-500 sm:text-[10px]">{ensemble.timestamps.filter((_, i) => i % 4 === 0).map((_, i) => <span key={i}>+{i * 12}h</span>)}</div></section>}
    </main>

    <footer className="flex items-center justify-between border-t border-slate-800 bg-[#070d18] px-4 py-2.5 font-mono text-xs text-slate-400 lg:px-8"><div>System: Online | Local simulation</div><div>WeatherNext 3</div></footer>
  </div>;
}

export default function App() {
  return <AppErrorBoundary><WeatherNextApp /></AppErrorBoundary>;
}
