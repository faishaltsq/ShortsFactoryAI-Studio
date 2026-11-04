import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

export const FONT_FAMILIES = {
  display: 'Fraunces',
  displayItalic: 'FrauncesItalic',
  body: 'Manrope',
  technical: 'IBM Plex Mono',
} as const;

export type FontFamilies = typeof FONT_FAMILIES;

const fontPromises: Promise<void>[] = [
  // Display (editorial serif) - Fraunces
  loadFont({
    family: FONT_FAMILIES.display,
    url: staticFile('fonts/Fraunces-Regular.woff2'),
    weight: '400',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.display,
    url: staticFile('fonts/Fraunces-SemiBold.woff2'),
    weight: '600',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.display,
    url: staticFile('fonts/Fraunces-SemiBoldItalic.woff2'),
    weight: '600',
    style: 'italic',
  }),
  loadFont({
    family: FONT_FAMILIES.displayItalic,
    url: staticFile('fonts/Fraunces-SemiBoldItalic.woff2'),
    weight: '600',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.displayItalic,
    url: staticFile('fonts/Fraunces-SemiBoldItalic.woff2'),
    weight: '600',
    style: 'italic',
  }),

  // Body (sans) - Manrope
  loadFont({
    family: FONT_FAMILIES.body,
    url: staticFile('fonts/Manrope-Regular.woff2'),
    weight: '400',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.body,
    url: staticFile('fonts/Manrope-Medium.woff2'),
    weight: '500',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.body,
    url: staticFile('fonts/Manrope-SemiBold.woff2'),
    weight: '600',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.body,
    url: staticFile('fonts/Manrope-Bold.woff2'),
    weight: '700',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.body,
    url: staticFile('fonts/Manrope-ExtraBold.woff2'),
    weight: '800',
    style: 'normal',
  }),

  // Technical (mono) - IBM Plex Mono
  loadFont({
    family: FONT_FAMILIES.technical,
    url: staticFile('fonts/IBMPlexMono-Regular.woff2'),
    weight: '400',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.technical,
    url: staticFile('fonts/IBMPlexMono-Medium.woff2'),
    weight: '500',
    style: 'normal',
  }),
  loadFont({
    family: FONT_FAMILIES.technical,
    url: staticFile('fonts/IBMPlexMono-SemiBold.woff2'),
    weight: '600',
    style: 'normal',
  }),
];

/**
 * Await all fonts to be loaded and registered in document.fonts.
 * Remotion's loadFont also calls delayRender/continueRender internally.
 */
export const waitForFonts = async (): Promise<void> => {
  await Promise.all(fontPromises);
};
