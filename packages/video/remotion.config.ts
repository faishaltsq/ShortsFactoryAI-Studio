import {Config} from '@remotion/cli/config';
import path from 'node:path';

// Generated job entries live outside this package. Resolve their installed
// dependencies here instead of relying on a machine-wide NODE_PATH or symlinks.
const dependencyDirectory = path.resolve('node_modules');
Config.overrideWebpackConfig((config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    modules: [
      ...(config.resolve?.modules ?? ['node_modules']),
      dependencyDirectory,
    ],
  },
}));

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer('angle-egl');
Config.setConcurrency(4);
Config.setDelayRenderTimeoutInMilliseconds(30000);
