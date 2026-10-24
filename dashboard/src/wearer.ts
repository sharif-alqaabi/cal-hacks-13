// Who wears the glasses, for the page's wording. Set VITE_WEARER_NAME in dashboard/.env; without it the page says "they".
export const WEARER = (import.meta.env.VITE_WEARER_NAME as string | undefined)?.trim() || ''
export const wearer = (fallback: string) => WEARER || fallback
