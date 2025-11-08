import React, { useState } from 'react';

export interface Tab {
  id: string;
  label: string;
  icon?: string;
  content: React.ReactNode;
}

interface TabPanelProps {
  tabs: Tab[];
  defaultTab?: string;
}

export default function TabPanel({ tabs, defaultTab }: TabPanelProps) {
  const [activeTab, setActiveTab] = useState(defaultTab || tabs[0]?.id);

  const activeTabContent = tabs.find(tab => tab.id === activeTab)?.content;

  return (
    <div className="h-full flex flex-col bg-scian-dark">
      {/* Tab Bar - VSCode style */}
      <div className="flex items-center bg-scian-panel border-b border-scian-border overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              px-4 py-2 text-sm font-medium transition-colors relative flex items-center gap-2
              ${activeTab === tab.id
                ? 'text-scian-text-primary bg-scian-dark border-b-2 border-scian-cyan'
                : 'text-scian-text-secondary hover:text-scian-text-primary hover:bg-scian-hover'
              }
            `}
          >
            {tab.icon && <span>{tab.icon}</span>}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto">
        {activeTabContent}
      </div>
    </div>
  );
}
