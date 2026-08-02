import { HeartHandshake } from 'lucide-react';

export function Goose({ className = '' }: { className?: string }) {
  return <HeartHandshake className={className} strokeWidth={1.75} aria-hidden="true" />;
}
