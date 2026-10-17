const path = require('path');
const {getDefaultConfig, mergeConfig} = require('@react-native/metro-config');

// The platform-independent protocol code lives in ../core and is imported by relative path (TypeScript source).
const core = path.resolve(__dirname, '../core');
module.exports = mergeConfig(getDefaultConfig(__dirname), {
  watchFolders: [core],
  resolver: {nodeModulesPaths: [path.resolve(__dirname, 'node_modules')]},
});
