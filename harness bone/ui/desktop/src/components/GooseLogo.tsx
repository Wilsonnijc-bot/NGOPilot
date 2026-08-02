import { Goose } from './icons/Goose';
import { cn } from '../utils';

interface GooseLogoProps {
  className?: string;
  size?: 'default' | 'small';
  hover?: boolean;
}

export default function GooseLogo({
  className = '',
  size = 'default',
  hover = true,
}: GooseLogoProps) {
  const sizes = {
    default: 'w-16 h-16',
    small: 'w-8 h-8',
  } as const;

  const currentSize = sizes[size];

  return (
    <div
      className={cn(
        className,
        currentSize,
        'flex items-center justify-center text-text-primary transition-transform duration-200',
        hover && 'hover:scale-105'
      )}
    >
      <Goose className="w-full h-full" />
    </div>
  );
}
