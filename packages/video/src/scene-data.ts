import type {SceneSpec} from './types';
import {OBJECT_KINDS, type ObjectKind} from './art/object-kinds';
import {ENVIRONMENTS, type EnvironmentKind} from './art/palette';

export {ENVIRONMENTS, type EnvironmentKind} from './art/palette';
export {OBJECT_KINDS, OBJECT_LABELS, isObjectKind, type ObjectKind} from './art/object-kinds';

export interface ComicData {title?: string; panels: {caption: string; speaker?: string; assetRef?: string}[]}
export interface TimelineData {title?: string; events: {date: string; label: string; detail?: string}[]}
export interface ParallaxData {title: string; caption?: string; layers: {depth: number; shape?: 'ridge' | 'city' | 'circle'; assetRef?: string}[]}
export interface InfographicData {title: string; items: {label: string; value: number; unit?: string}[]; maxValue?: number; decimals?: number}

/**
 * The informative engine's object vocabulary.
 *
 * A scene describes *things and their motion*. It never describes a person: there is no pose, no
 * expression, no gesture, no mouth. That is the whole migration — the object carries the meaning
 * and the motion carries the explanation.
 */

/** One object placed on the 1080x1920 stage. */
export interface StageObject {
  kind: ObjectKind;
  /** 0..1 centre on the stage. */
  x: number;
  y: number;
  /** Width as a fraction of the stage width. */
  size: number;
  /** Frames after scene start before the object arrives. Default 0. */
  at?: number;
  label?: string;
  /**
   * Inclusive frame window that lifts the object out of the scene: a glow, a scale, a brighter
   * tone. This is how a narration clause about one component reaches that component.
   */
  highlight?: [number, number];
}

/** A label anchored to an object, drawn near it rather than in a fixed type block. */
export interface CalloutSpec {
  /** Index into `objects`. */
  object: number;
  text: string;
  /** Offset from the object's centre, in stage fractions. */
  dx: number;
  dy: number;
  at?: number;
}

/** A directed link between two objects, drawn as a travelling packet path. */
export interface FlowSpec {
  from: number;
  to: number;
  label?: string;
  at?: number;
}

export interface ExplainerData {
  title?: string;
  caption?: string;
  environment: EnvironmentKind;
  objects: StageObject[];
  callouts: CalloutSpec[];
  flows: FlowSpec[];
  layoutMode?: 'DefaultHero' | 'SplitComparison' | 'RadialNetwork' | 'LeftRailProcess' | 'FullBleedFocus';
  causalState?: {
    initialState: string;
    causalAction: string;
    resultingState: string;
    transition: string;
  };
}

/** A staged sequence: each step is a node, and packets run the chain in order. */
export interface ProcessFlowData {
  title?: string;
  caption?: string;
  environment: EnvironmentKind;
  steps: {label: string; detail?: string}[];
}

/** A changing quantity: bars grow, numbers count. */
export interface MetricShiftData {
  title: string;
  caption?: string;
  environment: EnvironmentKind;
  metrics: {label: string; value: number; unit?: string}[];
  maxValue?: number;
  decimals?: number;
}

type ObjectData = Record<string, unknown>;
const object = (value: unknown, keys: string[]): ObjectData => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Template data must be an object');
  const data = value as ObjectData;
  if (Object.keys(data).some(k => !keys.includes(k))) throw new Error('Unsupported template data field');
  return data;
};
const text = (value: unknown, max: number, optional = false): void => {
  if (optional && value == null) return;
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('Missing or invalid template text');
};
const items = (value: unknown, min: number, max: number): ObjectData[] => {
  if (!Array.isArray(value) || value.length < min || value.length > max) throw new Error('Invalid template item count');
  return value as ObjectData[];
};
const number = (value: unknown, min: number, max: number): void => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error('Invalid finite template number');
};

/** Only content-addressed raster files staged by AssetAgent may become browser image requests. */
export const localImage = (src: string): string => {
  if (!/^assets\/[a-f0-9]{64}\.(png|jpe?g|webp)$/.test(src)) throw new Error('Image must be a staged local raster asset');
  return src;
};

const environment = (value: unknown): EnvironmentKind => {
  if (value == null) return 'abstract';
  if (typeof value !== 'string' || !(ENVIRONMENTS as readonly string[]).includes(value)) {
    throw new Error(`Unsupported environment: ${String(value)}`);
  }
  return value as EnvironmentKind;
};

const stageObject = (raw: unknown, index: number): StageObject => {
  const o = object(raw, ['kind', 'x', 'y', 'size', 'at', 'label', 'highlight']);
  if (typeof o.kind !== 'string' || !(OBJECT_KINDS as readonly string[]).includes(o.kind)) {
    throw new Error(`Unsupported object kind at index ${index}: ${String(o.kind)}`);
  }
  number(o.x, 0, 1);
  number(o.y, 0, 1);
  number(o.size, 0.1, 1.2);
  const out: StageObject = {kind: o.kind as ObjectKind, x: o.x as number, y: o.y as number, size: o.size as number};
  if (o.at != null) {
    number(o.at, 0, 3000);
    if (!Number.isInteger(o.at)) throw new Error(`Object ${index} at must be an integer frame`);
    out.at = o.at as number;
  }
  text(o.label, 40, true);
  if (o.label != null) out.label = o.label as string;
  if (o.highlight != null) {
    const h = o.highlight;
    if (!Array.isArray(h) || h.length !== 2) throw new Error(`Object ${index} highlight must be [start, end]`);
    number(h[0], 0, 3000);
    number(h[1], 0, 3000);
    if ((h[0] as number) > (h[1] as number)) throw new Error(`Object ${index} highlight window is reversed`);
    out.highlight = [h[0] as number, h[1] as number];
  }
  return out;
};

export function validateExplainerData(raw: unknown): ExplainerData {
  const d = object(raw, [
    'title',
    'caption',
    'environment',
    'objects',
    'callouts',
    'flows',
    'layoutMode',
    'layout_mode',
    'causalState',
    'causal_state',
  ]);
  const out: ExplainerData = {environment: environment(d.environment), objects: [], callouts: [], flows: []};
  text(d.title, 70, true);
  if (d.title != null) out.title = d.title as string;
  text(d.caption, 160, true);
  if (d.caption != null) out.caption = d.caption as string;
  const rawLayout = d.layoutMode ?? d.layout_mode;
  if (rawLayout != null) {
    const validModes = ['DefaultHero', 'SplitComparison', 'RadialNetwork', 'LeftRailProcess', 'FullBleedFocus'];
    if (typeof rawLayout !== 'string' || !validModes.includes(rawLayout)) {
      throw new Error(`Invalid layoutMode: ${String(rawLayout)}`);
    }
    out.layoutMode = rawLayout as 'DefaultHero' | 'SplitComparison' | 'RadialNetwork' | 'LeftRailProcess' | 'FullBleedFocus';
  }
  const rawCausal = d.causalState ?? d.causal_state;
  if (rawCausal != null) {
    const cs = object(rawCausal, [
      'initialState',
      'causalAction',
      'resultingState',
      'transition',
      'initial_state',
      'causal_action',
      'resulting_state',
    ]);
    const init = cs.initialState ?? cs.initial_state;
    const action = cs.causalAction ?? cs.causal_action;
    const result = cs.resultingState ?? cs.resulting_state;
    const trans = cs.transition;
    text(init, 500);
    text(action, 500);
    text(result, 500);
    text(trans, 500);
    out.causalState = {
      initialState: init as string,
      causalAction: action as string,
      resultingState: result as string,
      transition: trans as string,
    };
  }
  // A scene with no object has nothing to explain; an empty stage is the failure this engine
  // exists to prevent, so it is rejected here rather than rendered as a black frame.
  out.objects = items(d.objects, 1, 5).map(stageObject);
  for (const [i, item] of items(d.callouts ?? [], 0, 6).entries()) {
    const c = object(item, ['object', 'text', 'dx', 'dy', 'at']);
    number(c.object, 0, out.objects.length - 1);
    if (!Number.isInteger(c.object)) throw new Error(`Callout ${i} object must be an object index`);
    text(c.text, 48);
    number(c.dx, -0.6, 0.6);
    number(c.dy, -0.6, 0.6);
    const callout: CalloutSpec = {
      object: c.object as number,
      text: c.text as string,
      dx: c.dx as number,
      dy: c.dy as number,
    };
    if (c.at != null) {
      number(c.at, 0, 3000);
      callout.at = c.at as number;
    }
    out.callouts.push(callout);
  }
  for (const [i, item] of items(d.flows ?? [], 0, 5).entries()) {
    const f = object(item, ['from', 'to', 'label', 'at']);
    number(f.from, 0, out.objects.length - 1);
    number(f.to, 0, out.objects.length - 1);
    if (!Number.isInteger(f.from) || !Number.isInteger(f.to)) throw new Error(`Flow ${i} endpoints must be object indices`);
    if (f.from === f.to) throw new Error(`Flow ${i} starts and ends on the same object`);
    const flow: FlowSpec = {from: f.from as number, to: f.to as number};
    text(f.label, 32, true);
    if (f.label != null) flow.label = f.label as string;
    if (f.at != null) {
      number(f.at, 0, 3000);
      flow.at = f.at as number;
    }
    out.flows.push(flow);
  }
  return out;
}

export function validateProcessFlowData(raw: unknown): ProcessFlowData {
  const d = object(raw, ['title', 'caption', 'environment', 'steps']);
  const out: ProcessFlowData = {environment: environment(d.environment), steps: []};
  text(d.title, 70, true);
  if (d.title != null) out.title = d.title as string;
  text(d.caption, 160, true);
  if (d.caption != null) out.caption = d.caption as string;
  out.steps = items(d.steps, 2, 5).map((item) => {
    const s = object(item, ['label', 'detail']);
    text(s.label, 34);
    text(s.detail, 70, true);
    return {label: s.label as string, detail: s.detail as string | undefined};
  });
  return out;
}

export function validateMetricShiftData(raw: unknown): MetricShiftData {
  const d = object(raw, ['title', 'caption', 'environment', 'metrics', 'maxValue', 'decimals']);
  const out: MetricShiftData = {title: '', environment: environment(d.environment), metrics: []};
  text(d.title, 70);
  out.title = d.title as string;
  text(d.caption, 160, true);
  if (d.caption != null) out.caption = d.caption as string;
  if (d.maxValue != null) number(d.maxValue, Number.MIN_VALUE, 1e12);
  if (d.decimals != null) {
    number(d.decimals, 0, 2);
    if (!Number.isInteger(d.decimals)) throw new Error('decimals must be integer');
  }
  out.metrics = items(d.metrics, 1, 4).map((item) => {
    const m = object(item, ['label', 'value', 'unit']);
    text(m.label, 34);
    number(m.value, 0, 1e12);
    if (m.unit !== undefined && (typeof m.unit !== 'string' || m.unit.length > 16)) throw new Error('Invalid unit');
    return {label: m.label as string, value: m.value as number, unit: m.unit as string | undefined};
  });
  if (d.maxValue != null) {
    for (const m of out.metrics) {
      if (m.value > (d.maxValue as number)) throw new Error('Scale does not cover value');
    }
  }
  if (d.maxValue != null) out.maxValue = d.maxValue as number;
  if (d.decimals != null) out.decimals = d.decimals as number;
  return out;
}

export function validateSceneData(scene: SceneSpec): void {
  switch (scene.template) {
    case 'MotionComic': {
      const d = object(scene.data, ['title', 'panels']);
      text(d.title, 70, true);
      for (const panel of items(d.panels, 1, 3)) {
        const p = object(panel, ['caption', 'speaker', 'assetRef']);
        text(p.caption, 120); text(p.speaker, 32, true); text(p.assetRef, 200, true);
        if (p.assetRef) localImage(p.assetRef as string);
      }
      break;
    }
    case 'HistoricalTimeline': {
      const d = object(scene.data, ['title', 'events']);
      text(d.title, 70, true);
      for (const event of items(d.events, 2, 4)) {
        const e = object(event, ['date', 'label', 'detail']);
        text(e.date, 24); text(e.label, 70); text(e.detail, 100, true);
      }
      break;
    }
    case 'ParallaxStory': {
      const d = object(scene.data, ['title', 'caption', 'layers']);
      text(d.title, 70); text(d.caption, 160, true);
      for (const layer of items(d.layers, 1, 4)) {
        const l = object(layer, ['depth', 'shape', 'assetRef']);
        number(l.depth, 0.1, 1);
        if ((l.shape == null) === (l.assetRef == null)) throw new Error('Layer needs exactly one visual');
        if (l.shape != null && !['ridge', 'city', 'circle'].includes(String(l.shape))) throw new Error('Unsupported parallax shape');
        if (l.assetRef != null) {text(l.assetRef, 200); localImage(l.assetRef as string);}
      }
      break;
    }
    case 'InfographicMotion': {
      const d = object(scene.data, ['title', 'items', 'maxValue', 'decimals']);
      text(d.title, 70);
      if (d.maxValue != null) number(d.maxValue, Number.MIN_VALUE, 1e12);
      if (d.decimals != null) {number(d.decimals, 0, 2); if (!Number.isInteger(d.decimals)) throw new Error('decimals must be integer');}
      for (const item of items(d.items, 1, 4)) {
        const i = object(item, ['label', 'value', 'unit']);
        text(i.label, 52); number(i.value, 0, 1e12);
        if (i.unit !== undefined && (typeof i.unit !== 'string' || i.unit.length > 16)) throw new Error('Invalid unit');
        if (d.maxValue != null && (i.value as number) > (d.maxValue as number)) throw new Error('Scale does not cover value');
      }
      break;
    }
    case 'ObjectExplainer': validateExplainerData(scene.data); break;
    case 'ProcessFlow': validateProcessFlowData(scene.data); break;
    case 'MetricShift': validateMetricShiftData(scene.data); break;
    case 'KineticTypography': case 'EducationalExplainer': break;
    default: throw new Error(`Unsupported template: ${scene.template}`);
  }
  for (const ref of scene.assetRefs) localImage(ref);
  const rawSceneLayout = scene.layoutMode ?? (scene as unknown as {layout_mode?: unknown}).layout_mode;
  if (rawSceneLayout != null) {
    const validModes = ['DefaultHero', 'SplitComparison', 'RadialNetwork', 'LeftRailProcess', 'FullBleedFocus'];
    if (typeof rawSceneLayout !== 'string' || !validModes.includes(rawSceneLayout)) {
      throw new Error(`Invalid scene layoutMode: ${String(rawSceneLayout)}`);
    }
  }
  const rawSceneCausal = scene.causalState ?? (scene as unknown as {causal_state?: unknown}).causal_state;
  if (rawSceneCausal != null) {
    const cs = object(rawSceneCausal, [
      'initialState',
      'causalAction',
      'resultingState',
      'transition',
      'initial_state',
      'causal_action',
      'resulting_state',
    ]);
    text(cs.initialState ?? cs.initial_state, 500);
    text(cs.causalAction ?? cs.causal_action, 500);
    text(cs.resultingState ?? cs.resulting_state, 500);
    text(cs.transition, 500);
  }
}
