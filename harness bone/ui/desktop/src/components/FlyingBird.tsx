import { HeartHandshake } from 'lucide-react';

interface FlyingBirdProps {
  className?: string;
  cycleInterval?: number;
}

export default function FlyingBird({ className = '' }: FlyingBirdProps) {
  return (
    <div className={`animate-pulse ${className}`}>
      <HeartHandshake className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />
    </div>
  );
}
