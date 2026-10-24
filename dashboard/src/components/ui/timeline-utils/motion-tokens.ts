// The registry Timeline imports these but ships no file for them. One easing family for the whole dashboard:
// everything eases out, nothing overshoots.
export const motionTokens = {
  ease: {
    enter: [0.2, 0, 0, 1],
    standard: [0.4, 0, 0.2, 1],
  },
  duration: { fast: 0.14, standard: 0.22 },
  blur: { subtle: 2, soft: 4 },
  spring: {
    smooth: { type: 'spring', visualDuration: 0.4, bounce: 0 },
    snappy: { type: 'spring', visualDuration: 0.25, bounce: 0 },
    morph: { type: 'spring', visualDuration: 0.36, bounce: 0.1 },
  },
} as const
