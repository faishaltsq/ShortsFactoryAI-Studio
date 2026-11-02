#!/usr/bin/env node
import fs from 'node:fs';
import parser from '@babel/parser';
import traversePkg from '@babel/traverse';

const traverse = traversePkg.default || traversePkg;

const ALLOWED_PACKAGES = new Set(['react', 'remotion']);
const DISALLOWED_MODULES = new Set([
  'child_process',
  'cluster',
  'dgram',
  'dns',
  'fs',
  'http',
  'https',
  'net',
  'os',
  'process',
  'tls',
  'v8',
  'vm',
  'worker_threads',
]);

const DANGEROUS_IDENTIFIERS = new Set([
  'eval',
  'Function',
  'process',
  'child_process',
  'fs',
  'os',
  'net',
  'http',
  'https',
  'global',
  'globalThis',
  'window',
  'document',
  'fetch',
  'XMLHttpRequest',
  'WebSocket',
  'localStorage',
  'sessionStorage',
]);

const ILLEGAL_PATH_CHARS = /[:*?"<>|\\]/;

function resolveString(node, scope) {
  if (!node) return null;
  if (node.type === 'StringLiteral') return node.value;
  if (node.type === 'TemplateLiteral' && node.quasis.length === 1) return node.quasis[0].value.raw;
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    const l = resolveString(node.left, scope);
    const r = resolveString(node.right, scope);
    if (l !== null && r !== null) return l + r;
  }
  if (node.type === 'Identifier' && scope) {
    const binding = scope.getBinding(node.name);
    if (binding && binding.path && binding.path.node && binding.path.node.init) {
      return resolveString(binding.path.node.init, binding.scope);
    }
  }
  return null;
}

function isAllowedModule(clean) {
  if (!clean || typeof clean !== 'string') return false;
  clean = clean.trim();
  if (!clean) return false;

  for (let i = 0; i < clean.length; i++) {
    const code = clean.charCodeAt(i);
    if (code < 32 || code === 0) return false;
  }

  if (clean.startsWith('/') || clean.startsWith('\\') || (clean.length >= 2 && clean[1] === ':' && /^[a-zA-Z]$/.test(clean[0]))) {
    return false;
  }

  const normalizedName = clean.replace(/^node:/, '').split('/')[0];
  if (DISALLOWED_MODULES.has(normalizedName) || DISALLOWED_MODULES.has(clean)) {
    return false;
  }

  const parts = clean.replace(/\\/g, '/').split('/').filter(Boolean);
  const forbiddenDirs = new Set(['node_modules', 'config', 'secrets', 'core', '.env', '.git']);
  for (const p of parts) {
    if (forbiddenDirs.has(p) || p.toLowerCase().includes('secret') || p.toLowerCase().includes('config')) {
      return false;
    }
  }

  if (ALLOWED_PACKAGES.has(clean)) return true;

  if (clean.startsWith('@remotion/')) {
    const subpath = clean.slice('@remotion/'.length);
    if (!subpath || ILLEGAL_PATH_CHARS.test(subpath)) return false;
    const subparts = subpath.split('/');
    if (subparts.some((p) => p === '..' || p === '.' || p === '')) return false;
    return true;
  }

  if (clean.startsWith('./') || clean.startsWith('../')) {
    if (ILLEGAL_PATH_CHARS.test(clean)) return false;
    if (clean.startsWith('./') && !parts.includes('..')) return true;

    let videoIdx = -1;
    for (let i = 0; i < parts.length - 1; i++) {
      if (parts[i] === 'video' && parts[i + 1] === 'src') {
        videoIdx = i;
        break;
      }
    }
    if (videoIdx !== -1) {
      const beforeVideo = parts.slice(0, videoIdx);
      if (beforeVideo.every((p) => p === '..' || p === 'packages')) {
        const afterSrc = parts.slice(videoIdx + 2);
        if (afterSrc.length > 0 && !afterSrc.some((p) => p === '..' || p === '.')) {
          return true;
        }
      }
    }
    return false;
  }

  if (clean.startsWith('packages/video/src/')) {
    const subpath = clean.slice('packages/video/src/'.length);
    if (!subpath || ILLEGAL_PATH_CHARS.test(subpath)) return false;
    const subparts = subpath.split('/');
    if (subparts.some((p) => p === '..' || p === '.')) return false;
    return true;
  }

  return false;
}

export function validateAST(code, filename = 'snippet.tsx') {
  const issues = [];
  const importedModules = [];

  let ast;
  try {
    ast = parser.parse(code, {
      sourceType: 'module',
      plugins: ['jsx', 'typescript'],
    });
  } catch (err) {
    return {
      valid: false,
      issues: [`${filename}: Parse error: ${err.message}`],
      imported_modules: [],
    };
  }

  traverse(ast, {
    ImportDeclaration(path) {
      const mod = path.node.source.value;
      importedModules.push(mod);
      if (!isAllowedModule(mod)) {
        issues.push(`${filename}: Disallowed import: ${mod}`);
      }
    },
    ExportNamedDeclaration(path) {
      if (path.node.source) {
        const mod = path.node.source.value;
        importedModules.push(mod);
        if (!isAllowedModule(mod)) {
          issues.push(`${filename}: Disallowed import: ${mod}`);
        }
      }
    },
    ExportAllDeclaration(path) {
      if (path.node.source) {
        const mod = path.node.source.value;
        importedModules.push(mod);
        if (!isAllowedModule(mod)) {
          issues.push(`${filename}: Disallowed import: ${mod}`);
        }
      }
    },
    CallExpression(path) {
      if (path.node.callee.type === 'Import') {
        issues.push(`${filename}: Forbidden token or call: 'dynamic import()'`);
      } else if (path.node.callee.type === 'Identifier') {
        const name = path.node.callee.name;
        if (name === 'require') {
          issues.push(`${filename}: Forbidden token or call: 'require'`);
        } else if (name === 'eval') {
          issues.push(`${filename}: Forbidden token or call: 'eval'`);
        } else if (name === 'Function') {
          issues.push(`${filename}: Forbidden token or call: 'Function()'`);
        } else if (name === 'fetch') {
          issues.push(`${filename}: Forbidden token or call: 'fetch()'`);
        }
      }
    },
    Identifier(path) {
      const name = path.node.name;
      if (DANGEROUS_IDENTIFIERS.has(name)) {
        // Disallow dangerous identifiers unless it's an object property key in an uncomputed expression (e.g. { window: 1 })
        if (path.parent.type === 'MemberExpression' && path.parent.property === path.node && !path.parent.computed) {
          // e.g. obj.window or obj.fetch - still dangerous if obj is window/globalThis
          const objName = path.parent.object && path.parent.object.name;
          if (objName === 'window' || objName === 'globalThis' || objName === 'document') {
            issues.push(`${filename}: Forbidden token or call: '${objName}.${name}'`);
          }
        } else if (path.parent.type === 'ObjectProperty' && path.parent.key === path.node && !path.parent.computed) {
          // Safe object key definition
        } else {
          issues.push(`${filename}: Forbidden token or call: '${name}'`);
        }
      }
    },
    MemberExpression(path) {
      let propValue = null;
      if (!path.node.computed && path.node.property.type === 'Identifier') {
        propValue = path.node.property.name;
      } else if (path.node.computed) {
        propValue = resolveString(path.node.property, path.scope);
      }

      if (propValue && (propValue === 'constructor' || propValue === '__proto__' || propValue === 'prototype')) {
        issues.push(`${filename}: Forbidden token or call: 'constructor access'`);
      }
    },
  });

  const dedupedImports = Array.from(new Set(importedModules));
  const dedupedIssues = Array.from(new Set(issues));

  return {
    valid: dedupedIssues.length === 0,
    issues: dedupedIssues,
    imported_modules: dedupedImports,
  };
}

if (process.argv[1] && process.argv[1].endsWith('ast_guard.mjs')) {
  let source = '';
  const inputArg = process.argv[2];
  if (inputArg && fs.existsSync(inputArg)) {
    source = fs.readFileSync(inputArg, 'utf8');
  } else {
    source = fs.readFileSync(0, 'utf8');
  }
  const result = validateAST(source, inputArg || 'snippet.tsx');
  console.log(JSON.stringify(result));
}
