/**
 * Resolver hook for `node scripts/test-adapter.mjs`.
 *
 * The adapter and the donor modules it imports use extensionless relative specifiers
 * (`./character/ids`), which the bundler resolves but Node's type-stripping loader does not.
 * On a resolution miss this retries the same specifier with a `.ts` suffix. Nothing else is
 * rewritten, and no file is read differently than by `tsc`.
 */
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context);
  } catch (err) {
    if (specifier.startsWith('.') && !specifier.endsWith('.ts')) {
      try {
        return await next(`${specifier}.ts`, context);
      } catch {
        // Fall through to the original error: it names the real unresolved specifier.
      }
    }
    throw err;
  }
}
