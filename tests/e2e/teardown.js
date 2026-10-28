const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');

module.exports = async () => {
  const dataDirectory = process.env.PHOTO_EDITOR_E2E_DATA_DIR;
  if (dataDirectory) {
    try {
      fs.rmSync(dataDirectory, { recursive: true, force: true });
    } catch (_) {}
  }

  // Secure default tracing: never publish trace archives in CI or without explicit opt-in.
  // When traces are not opted-in, purge all archives unconditionally.
  // When local opt-in tracing is active, run the strict fail-closed structured sanitizer.
  const resultsDir = path.join(__dirname, '..', '..', 'test-results');
  const reportDir = path.join(__dirname, '..', '..', 'playwright-report');
  if (fs.existsSync(reportDir)) {
    try {
      fs.rmSync(reportDir, { recursive: true, force: true });
    } catch (_) {}
  }

  if (fs.existsSync(resultsDir)) {
    const purgeSensitiveArtifacts = (dir) => {
      if (!fs.existsSync(dir)) return;
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          purgeSensitiveArtifacts(fullPath);
        } else if (entry.isFile() && (
          entry.name.endsWith('.zip') ||
          entry.name.endsWith('.tmp') ||
          entry.name.endsWith('.png') ||
          entry.name.endsWith('.har')
        )) {
          try {
            fs.rmSync(fullPath, { force: true });
          } catch (_) {}
        }
      }
    };

    const purgeZipAndTmp = (dir) => {
      if (!fs.existsSync(dir)) return;
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          purgeZipAndTmp(fullPath);
        } else if (entry.isFile() && (entry.name.endsWith('.zip') || entry.name.endsWith('.tmp'))) {
          try {
            fs.rmSync(fullPath, { force: true });
          } catch (_) {}
        }
      }
    };

    const isCI = Boolean(process.env.CI) || Boolean(process.env.GITHUB_ACTIONS);
    const traceOptIn = !isCI && ['1', 'true'].includes(String(process.env.PLAYWRIGHT_ENABLE_TRACE || '').toLowerCase());

    if (isCI || !traceOptIn) {
      // In CI or default local runs, purge all sensitive trace archives and artifacts
      purgeSensitiveArtifacts(resultsDir);
    } else {
      const python = process.env.ODYSSEUS_TEST_PYTHON || 'python';
      const sanitizerScript = path.join(__dirname, '..', '..', 'scripts', 'sanitize_trace_artifacts.py');
      let sanitizerSucceeded = false;
      try {
        execSync(`${JSON.stringify(python)} ${JSON.stringify(sanitizerScript)} ${JSON.stringify(resultsDir)}`, {
          stdio: 'ignore',
          timeout: 30_000,
        });
        sanitizerSucceeded = true;
      } catch (_) {
        sanitizerSucceeded = false;
      }

      if (!sanitizerSucceeded) {
        // Fail closed: purge all remaining zip or tmp archives
        purgeZipAndTmp(resultsDir);
      }
    }
  }
};
