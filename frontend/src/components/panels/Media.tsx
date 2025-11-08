import React from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import MediaGrid from './MediaGrid';
import MediaEditor from './MediaEditor';

export default function Media() {
  const tabs: Tab[] = [
    {
      id: 'library',
      label: 'Library',
      content: <MediaGrid />,
    },
    {
      id: 'editor',
      label: 'Editor',
      content: <MediaEditor />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="library" />;
}
