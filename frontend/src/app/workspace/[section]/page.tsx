'use client';

import Link from 'next/link';
import { Suspense } from 'react';
import { ArrowLeft, Bot, CheckCircle2, Database, Info } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { OperationsWorkspace } from '@/components/operations/OperationsWorkspace';
import { AgentWorkspace } from '@/components/agents/AgentWorkspace';
import { TasksWorkspace } from '@/components/tasks/TasksWorkspace';
import { VisionTwinWorkspace } from '@/components/vision/VisionTwinWorkspace';

const sections: Record<string, { title: string; description: string; status: 'available' | 'planned' }> = {
  operations: {
    title: 'Operations',
    description: 'Operational workflows are currently centered on the IT Helpdesk investigation flow.',
    status: 'available',
  },
  agents: {
    title: 'AI Agents',
    description: 'The agent catalog currently exposes the implemented IT Helpdesk worker through task creation.',
    status: 'available',
  },
  tasks: {
    title: 'Tasks & Incidents',
    description: 'Task history and investigation details are available in the Command Center while persistent case navigation is being built.',
    status: 'available',
  },
  approvals: {
    title: 'Approvals',
    description: 'No approval action is currently exposed by the backend. Sensitive actions remain unavailable rather than simulated.',
    status: 'planned',
  },
  insights: {
    title: 'Insights & Analytics',
    description: 'Analytics views will be connected when measured task and token metrics are available.',
    status: 'planned',
  },
  integrations: {
    title: 'Integrations',
    description: 'Workspace ini menggunakan data ilustrasi kampus; integrasi live belum terhubung.',
    status: 'planned',
  },
  settings: {
    title: 'Settings',
    description: 'Workspace settings are not implemented in the current MVP.',
    status: 'planned',
  },
};

export default function WorkspaceSectionPage({ params }: { params: { section: string } }) {
  if (params.section === 'operations') return <Suspense fallback={<p role="status">Memuat Operations...</p>}><OperationsWorkspace /></Suspense>;
  if (params.section === 'agents') return <AgentWorkspace />;
  if (params.section === 'tasks') return <TasksWorkspace />;
  if (params.section === 'vision-twin') return <VisionTwinWorkspace />;
  if (params.section === 'approvals') return <TasksWorkspace initialStatusFilter="waiting_for_approval" />;

  const section = sections[params.section] ?? {
    title: 'Workspace',
    description: 'This workspace section is not available.',
    status: 'planned' as const,
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-textSecondary hover:text-textPrimary">
        <ArrowLeft className="h-4 w-4" />
        Kembali ke Command Center
      </Link>
      <div>
        <div className="mb-3 flex gap-2">
          <Badge variant={section.status === 'available' ? 'success' : 'secondary'}>
            {section.status === 'available' ? 'AVAILABLE' : 'PLANNED'}
          </Badge>
          <Badge variant="info">Unified workspace</Badge>
        </div>
        <h1 className="text-3xl font-semibold text-textPrimary">{section.title}</h1>
        <p className="mt-2 text-textSecondary">{section.description}</p>
      </div>
      <Card className="p-6">
        <div className="flex items-start gap-4">
          {params.section === 'agents' ? <Bot className="h-6 w-6 text-indigo-600" /> : params.section === 'integrations' ? <Database className="h-6 w-6 text-indigo-600" /> : section.status === 'available' ? <CheckCircle2 className="h-6 w-6 text-green-600" /> : <Info className="h-6 w-6 text-amber-600" />}
          <div>
            <h2 className="font-semibold text-textPrimary">Current MVP scope</h2>
            <p className="mt-2 text-sm leading-6 text-textSecondary">
              Role-specific use cases are selected when creating a task. This keeps the workspace unified and prevents unsupported capabilities from appearing as live applications.
            </p>
            <Button className="mt-4" onClick={() => window.location.assign('/')}>Open Command Center</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
