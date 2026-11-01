import type React from 'react';
import type {TemplateId} from '../types';
import type {SceneProps} from '../components/NarrativeFrame';
import {KineticTypographyScene} from './KineticTypography';
import {EducationalExplainerScene} from './EducationalExplainer';
import {MotionComicScene} from './MotionComic';
import {HistoricalTimelineScene} from './HistoricalTimeline';
import {ParallaxStoryScene} from './ParallaxStory';
import {InfographicMotionScene} from './InfographicMotion';
import {ObjectExplainerScene} from './ObjectExplainer';
import {ProcessFlowScene} from './ProcessFlow';
import {MetricShiftScene} from './MetricShift';

export const SCENE_RENDERERS: Record<TemplateId, React.FC<SceneProps>> = {
  KineticTypography: KineticTypographyScene,
  EducationalExplainer: EducationalExplainerScene,
  MotionComic: MotionComicScene,
  HistoricalTimeline: HistoricalTimelineScene,
  ParallaxStory: ParallaxStoryScene,
  InfographicMotion: InfographicMotionScene,
  ObjectExplainer: ObjectExplainerScene,
  ProcessFlow: ProcessFlowScene,
  MetricShift: MetricShiftScene,
};
