/**
 * Resolver hook for `node scripts/test-adapter.mjs`.
 *
 * The adapter and the donor modules it imports use extensionless relative specifiers
 * (`./character/ids`), which the bundler resolves but Node's type-stripping loader does not.
 * On a resolution miss this retries the same specifier with a `.ts` suffix, then `.tsx` — the
 * object library and the compositions are `.tsx`, and a `.ts`-only retry cannot see them.
 */
export async function resolve(specifier, context, next) {
  try {
    return await next(specifier, context);
  } catch (err) {
    if (specifier.startsWith('.') && !/\.tsx?$/.test(specifier)) {
      for (const suffix of ['.ts', '.tsx']) {
        try {
          return await next(`${specifier}${suffix}`, context);
        } catch {
          // Try the next suffix; the original error is rethrown below if none resolve.
        }
      }
    }
    throw err;
  }
}
