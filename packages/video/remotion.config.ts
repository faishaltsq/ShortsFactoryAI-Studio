import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer('angle-egl');
Config.setConcurrency(4);
Config.setDelayRenderTimeoutInMilliseconds(30000);
