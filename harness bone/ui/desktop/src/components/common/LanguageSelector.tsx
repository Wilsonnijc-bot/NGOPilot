import { useEffect, useState } from 'react';
import { ChevronDown, Languages } from 'lucide-react';
import { currentLocale, defineMessages, useIntl } from '../../i18n';
import {
  DEFAULT_LANGUAGE_SETTING,
  normalizeLanguageSetting,
  type LanguageSetting,
} from '../../utils/settings';
import { cn } from '../../utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';

const i18n = defineMessages({
  language: { id: 'settings.language.title', defaultMessage: 'Language' },
});

const LANGUAGE_OPTIONS: ReadonlyArray<{ value: LanguageSetting; label: string }> = [
  { value: 'zh-HK', label: '廣東話' },
  { value: 'en', label: 'English' },
];

interface LanguageSelectorProps {
  className?: string;
  menuAlign?: 'start' | 'center' | 'end';
}

export function LanguageSelector({ className, menuAlign = 'end' }: LanguageSelectorProps) {
  const intl = useIntl();
  const [language, setLanguage] = useState<LanguageSetting>(() =>
    currentLocale.toLowerCase().startsWith('en') ? 'en' : DEFAULT_LANGUAGE_SETTING
  );
  const [isChanging, setIsChanging] = useState(false);

  useEffect(() => {
    let active = true;

    window.electron
      .getSetting('language')
      .then((value) => {
        if (active) setLanguage(normalizeLanguageSetting(value));
      })
      .catch((error) => console.error('Failed to load language setting:', error));

    return () => {
      active = false;
    };
  }, []);

  const handleLanguageChange = async (value: string) => {
    const nextLanguage = normalizeLanguageSetting(value);
    if (nextLanguage === language || isChanging) return;

    const previousLanguage = language;
    setLanguage(nextLanguage);
    setIsChanging(true);

    try {
      await window.electron.setSetting('language', nextLanguage);
      window.electron.reloadApp();
    } catch (error) {
      console.error('Failed to update language setting:', error);
      setLanguage(previousLanguage);
      setIsChanging(false);
    }
  };

  const selectedLanguage =
    LANGUAGE_OPTIONS.find((option) => option.value === language) ?? LANGUAGE_OPTIONS[0];
  const languageLabel = intl.formatMessage(i18n.language);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`${languageLabel}: ${selectedLanguage.label}`}
        disabled={isChanging}
        className={cn(
          'flex h-9 items-center justify-between gap-2 rounded-md border border-border-primary bg-background-primary px-3 text-sm text-text-primary outline-none transition-colors hover:bg-background-secondary focus-visible:ring-1 focus-visible:ring-border-active disabled:cursor-wait disabled:opacity-60',
          className
        )}
      >
        <Languages aria-hidden="true" className="size-4 text-text-secondary" />
        <span className="truncate">{selectedLanguage.label}</span>
        <ChevronDown aria-hidden="true" className="size-4 text-text-secondary" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={menuAlign}
        className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-[9rem]"
      >
        <DropdownMenuRadioGroup value={language} onValueChange={handleLanguageChange}>
          {LANGUAGE_OPTIONS.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
