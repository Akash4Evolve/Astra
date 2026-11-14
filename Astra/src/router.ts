import { useEffect, useState } from 'react';

/** Tiny hash router: #/overview, #/alerts/al-rhr-001, … */
export const go = (path: string) => {
  window.location.hash = path;
};

export function useRoute(): string[] {
  const parse = () => (window.location.hash.replace(/^#\/?/, '') || 'overview').split('/');
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}
