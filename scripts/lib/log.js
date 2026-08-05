/**
 * Status logging helpers.
 */

/**
 * @param {number} step
 * @param {number} total
 * @param {string} message
 */
export function step(stepNumber, total, message) {
  console.log(`\n[${stepNumber}/${total}] ${message}`);
}

/**
 * @param {string} message
 */
export function info(message) {
  console.log(`  ${message}`);
}

/**
 * @param {string} message
 */
export function success(message) {
  console.log(`  ✓ ${message}`);
}

/**
 * @param {string} message
 */
export function warn(message) {
  console.warn(`  ! ${message}`);
}

/**
 * @param {string} message
 */
export function fail(message) {
  console.error(`\nSetup failed:\n${message}\n`);
}
