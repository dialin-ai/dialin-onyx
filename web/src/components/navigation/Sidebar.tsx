import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';

export function Sidebar() {
  const pathname = usePathname();

  const navigationItems = [
    {
      name: 'Marketing Content Analysis',
      href: '/chat/marketing',
      icon: '📊'
    }
  ];

  return (
    <div className="w-64 h-screen bg-card border-r border-border flex flex-col shadow-sm">
      <div className="p-4 border-b border-border bg-card transition-colors hover:bg-muted/50">
        <h2 className="text-lg font-semibold text-foreground">Chats</h2>
      </div>
      <nav className="flex-1 p-4">
        <ul className="space-y-2">
          {navigationItems.map((item) => (
            <li key={item.href}>
              <Link 
                href={item.href}
                className={cn(
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-all duration-200 ease-in-out',
                  'transform hover:translate-x-1',
                  'ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                  pathname === item.href 
                    ? 'bg-primary/10 text-primary hover:bg-primary/15 shadow-sm' 
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground hover:shadow-sm'
                )}
              >
                <span className="transition-transform duration-200 group-hover:scale-110">{item.icon}</span>
                <span>{item.name}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
} 