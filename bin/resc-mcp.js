#!/usr/bin/env node

/**
 * resc MCP Server Launcher & Bridge
 * Provides cross-platform npx execution for the native Rust MCP server.
 *
 * Usage:
 *   npx resc-mcp [flags]
 *   node bin/resc-mcp.js [flags]
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const isWindows = process.platform === 'win32';
const binaryName = isWindows ? 'mcp-server.exe' : 'mcp-server';

function findBinary() {
  if (process.env.RESC_MCP_BIN && fs.existsSync(process.env.RESC_MCP_BIN)) {
    return process.env.RESC_MCP_BIN;
  }
  if (process.env.RECOVERYAI_MCP_BIN && fs.existsSync(process.env.RECOVERYAI_MCP_BIN)) {
    return process.env.RECOVERYAI_MCP_BIN;
  }

  const searchPaths = [
    path.resolve(__dirname, '..', 'target', 'release', binaryName),
    path.resolve(__dirname, '..', 'target', 'debug', binaryName),
    path.resolve(__dirname, '..', 'binaries', binaryName),
    path.resolve(__dirname, binaryName)
  ];

  for (const candidate of searchPaths) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
}

function run() {
  const backend = process.env.RESC_BACKEND || 'auto';
  if (!['auto', 'native', 'python'].includes(backend)) {
    console.error('RESC_BACKEND must be auto, native or python');
    process.exit(1);
  }
  const configured = process.env.RESC_MCP_BIN || process.env.RECOVERYAI_MCP_BIN;
  if (backend !== 'python' && configured && !fs.existsSync(configured)) {
    console.error('Configured MCP binary does not exist');
    process.exit(1);
  }
  let binaryPath = backend === 'python' ? null : findBinary();
  let prefixArgs = [];

  if (!binaryPath) {
    if (backend === 'native') {
      console.error('Native engine unavailable. Build with cargo build --release --locked.');
      process.exit(1);
    }
    binaryPath = process.env.RESC_PYTHON || (isWindows ? 'python' : 'python3');
    prefixArgs = [path.resolve(__dirname, '..', 'scripts', 'mcp_server_engine.py')];
    console.error('[resc] Limited Python diagnostics: no sessions, overlay repairs or extraction.');
  }

  const userArgs = process.argv.slice(2);

  const child = spawn(binaryPath, [...prefixArgs, ...userArgs], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: {
      ...process.env,
      RUST_LOG: process.env.RUST_LOG || 'info'
    }
  });

  process.stdin.pipe(child.stdin);
  child.stdout.pipe(process.stdout);

  child.on('error', (err) => {
    console.error(`[resc MCP Launcher] Failed to start native process (${binaryPath}):`, err);
    process.exit(1);
  });

  child.on('close', (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });

  process.on('SIGINT', () => {
    if (!child.killed) child.kill('SIGINT');
  });

  process.on('SIGTERM', () => {
    if (!child.killed) child.kill('SIGTERM');
  });
}

run();
