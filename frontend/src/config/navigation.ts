import type { LucideIcon } from 'lucide-react';
import {
  BarChart3,
  Bot,
  CheckSquare,
  Camera,
  Database,
  LayoutDashboard,
  Network,
  Settings,
} from 'lucide-react';

export interface NavigationItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const navigationItems: NavigationItem[] = [
  { label: 'Command Center', href: '/', icon: LayoutDashboard },
  { label: 'Operations', href: '/workspace/operations', icon: Network },
  { label: 'Vision Twin', href: '/workspace/vision-twin', icon: Camera },
  { label: 'AI Agents', href: '/workspace/agents', icon: Bot },
  { label: 'Tasks & Incidents', href: '/workspace/tasks', icon: CheckSquare },
  { label: 'Approvals', href: '/workspace/approvals', icon: CheckSquare },
  { label: 'Insights & Analytics', href: '/workspace/insights', icon: BarChart3 },
  { label: 'Integrations', href: '/workspace/integrations', icon: Database },
  { label: 'Settings', href: '/workspace/settings', icon: Settings },
];
