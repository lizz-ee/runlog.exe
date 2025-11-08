import React, { useState, useEffect } from 'react';
import { Mosaic, MosaicWindow, MosaicDragType, MosaicDropTargetPosition, createBalancedTreeFromLeaves, MosaicNode } from 'react-mosaic-component';
import 'react-mosaic-component/react-mosaic-component.css';
import './App.css';
import { AppProvider } from './contexts/AppContext';

// Import panel components
import MediaGrid from './components/panels/MediaGrid';
import MediaEditor from './components/panels/MediaEditor';
import PostEditor from './components/panels/PostEditor';
import Calendar from './components/panels/Calendar';
import Analytics from './components/panels/Analytics';
import AIAssistant from './components/panels/AIAssistant';
import FeedPreview from './components/panels/FeedPreview';
import LiveFeed from './components/panels/LiveFeed';
import Inbox from './components/panels/Inbox';

type ViewId = 'library' | 'mediaeditor' | 'editor' | 'calendar' | 'analytics' | 'ai' | 'feed' | 'livefeed' | 'inbox';

const PANEL_TITLES: Record<ViewId, string> = {
  library: 'Media Library',
  mediaeditor: 'Media Editor',
  editor: 'Post Editor',
  calendar: 'Calendar',
  analytics: 'Analytics',
  ai: 'AI Assistant',
  feed: 'Feed Preview',
  livefeed: 'Live Feed',
  inbox: 'Inbox',
};

const PANEL_COMPONENTS: Record<ViewId, React.ComponentType> = {
  library: MediaGrid,
  mediaeditor: MediaEditor,
  editor: PostEditor,
  calendar: Calendar,
  analytics: Analytics,
  ai: AIAssistant,
  feed: FeedPreview,
  livefeed: LiveFeed,
  inbox: Inbox,
};

// Panel icons and colors for toolbar
const PANEL_ICONS: Record<ViewId, { icon: string; color: string; description: string }> = {
  library: { icon: '🖼️', color: 'from-scian-cyan to-scian-blue', description: 'Media Library' },
  mediaeditor: { icon: '✨', color: 'from-scian-peach to-scian-violet', description: 'Media Editor' },
  editor: { icon: '✍️', color: 'from-scian-violet to-scian-blue', description: 'Post Editor' },
  calendar: { icon: '📅', color: 'from-scian-green to-scian-cyan', description: 'Calendar' },
  analytics: { icon: '📊', color: 'from-scian-blue to-scian-violet', description: 'Analytics' },
  ai: { icon: '🤖', color: 'from-scian-cyan to-scian-peach', description: 'AI Assistant' },
  feed: { icon: '👁️', color: 'from-platform-instagram-start via-platform-instagram-mid to-platform-instagram-end', description: 'Feed Preview' },
  livefeed: { icon: '📡', color: 'from-scian-green to-scian-blue', description: 'Live Feed' },
  inbox: { icon: '💬', color: 'from-scian-peach to-scian-cyan', description: 'Inbox' },
};

// Draggable Panel Icon Component
function DraggablePanelIcon({ viewId, onAddPanel }: { viewId: ViewId; onAddPanel: (id: ViewId) => void }) {
  const panelInfo = PANEL_ICONS[viewId];
  const [isDragging, setIsDragging] = useState(false);

  const handleDragStart = (e: React.DragEvent) => {
    setIsDragging(true);
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('application/mosaic-panel', viewId);

    // Create custom drag preview
    const dragImage = document.createElement('div');
    dragImage.textContent = panelInfo.icon;
    dragImage.style.fontSize = '32px';
    dragImage.style.position = 'absolute';
    dragImage.style.top = '-1000px';
    document.body.appendChild(dragImage);
    e.dataTransfer.setDragImage(dragImage, 16, 16);
    setTimeout(() => document.body.removeChild(dragImage), 0);
  };

  const handleDragEnd = () => {
    setIsDragging(false);
  };

  const handleClick = () => {
    onAddPanel(viewId);
  };

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onClick={handleClick}
      className={`group relative px-3 py-2 rounded-lg cursor-pointer transition-all hover:scale-110 bg-gradient-to-r ${panelInfo.color} bg-opacity-10 hover:bg-opacity-20 border border-transparent hover:border-scian-cyan/30 hover:shadow-lg hover:shadow-scian-cyan/20 ${isDragging ? 'opacity-50' : ''}`}
      title={`${panelInfo.description} - Click or drag to add`}
    >
      <span className="text-xl">{panelInfo.icon}</span>
      {/* Tooltip on hover */}
      <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-scian-panel rounded text-xs text-scian-text-primary border border-scian-border whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none shadow-lg">
        {panelInfo.description}
        <div className="text-scian-cyan text-[10px] mt-0.5">Click to add</div>
      </div>
    </div>
  );
}

function App() {
  const initialLayout = {
    direction: 'row',
    first: {
      direction: 'column',
      first: 'library',
      second: 'ai',
      splitPercentage: 50,
    },
    second: {
      direction: 'row',
      first: {
        direction: 'column',
        first: {
          direction: 'row',
          first: 'mediaeditor',
          second: 'editor',
          splitPercentage: 50,
        },
        second: 'calendar',
        splitPercentage: 50,
      },
      second: {
        direction: 'row',
        first: {
          direction: 'column',
          first: 'feed',
          second: 'inbox',
          splitPercentage: 50,
        },
        second: {
          direction: 'column',
          first: 'livefeed',
          second: 'analytics',
          splitPercentage: 50,
        },
        splitPercentage: 50,
      },
      splitPercentage: 40,
    },
    splitPercentage: 20,
  };

  // Load saved layout from localStorage or use default
  const [currentNode, setCurrentNode] = useState<any>(() => {
    const savedLayoutStr = localStorage.getItem('scian-layout');
    if (savedLayoutStr) {
      try {
        return JSON.parse(savedLayoutStr);
      } catch (e) {
        console.error('Failed to parse saved layout:', e);
        return initialLayout;
      }
    }
    return initialLayout;
  });
  const [expandedPanel, setExpandedPanel] = useState<ViewId | null>(null);
  const [savedLayout, setSavedLayout] = useState<any>(null);

  // Save layout to localStorage
  const saveLayout = () => {
    localStorage.setItem('scian-layout', JSON.stringify(currentNode));
    // Show a brief success message
    const btn = document.getElementById('save-layout-btn');
    if (btn) {
      const originalText = btn.textContent;
      btn.textContent = '✓ Saved!';
      btn.style.backgroundColor = 'rgba(79, 195, 247, 0.2)';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.style.backgroundColor = '';
      }, 1500);
    }
  };

  // Auto-save on window close
  useEffect(() => {
    const handleBeforeUnload = () => {
      localStorage.setItem('scian-layout', JSON.stringify(currentNode));
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [currentNode]);

  const handleExpand = (id: ViewId) => {
    if (expandedPanel === id) {
      // Restore previous layout
      if (savedLayout) {
        setCurrentNode(savedLayout);
      }
      setExpandedPanel(null);
      setSavedLayout(null);
    } else {
      // Save current layout and expand
      setSavedLayout(currentNode);
      setCurrentNode(id); // Set to just the single panel ID
      setExpandedPanel(id);
    }
  };

  const handleClose = (id: ViewId) => {
    // Remove the panel from the mosaic tree
    const removeNode = (node: any): any => {
      if (typeof node === 'string') {
        return node === id ? null : node;
      }
      if (node && typeof node === 'object') {
        const first = removeNode(node.first);
        const second = removeNode(node.second);

        if (first === null && second === null) return null;
        if (first === null) return second;
        if (second === null) return first;

        return { ...node, first, second };
      }
      return node;
    };

    const newNode = removeNode(currentNode);
    if (newNode) {
      setCurrentNode(newNode);
    }
  };

  const handleAddPanel = (id: ViewId) => {
    // Check if panel already exists in the layout
    const panelExists = (node: any): boolean => {
      if (!node) return false;
      if (typeof node === 'string') return node === id;
      return panelExists(node.first) || panelExists(node.second);
    };

    if (panelExists(currentNode)) {
      // Panel already exists, don't add it again
      console.log(`Panel ${id} already exists in the layout`);
      return;
    }

    // If in expanded mode, exit it first
    if (expandedPanel !== null) {
      if (savedLayout) {
        setCurrentNode(savedLayout);
      }
      setExpandedPanel(null);
      setSavedLayout(null);
    }

    // Add panel to the layout
    if (!currentNode) {
      setCurrentNode(id);
    } else if (typeof currentNode === 'string') {
      // If there's only one panel, split horizontally
      setCurrentNode({
        direction: 'row',
        first: currentNode,
        second: id,
        splitPercentage: 50,
      });
    } else {
      // Add to the bottom-right corner (column split)
      setCurrentNode({
        direction: 'column',
        first: currentNode,
        second: id,
        splitPercentage: 75,
      });
    }
  };

  const renderTile = (id: ViewId, path: any[]) => {
    const Component = PANEL_COMPONENTS[id];
    const isExpanded = expandedPanel === id;

    return (
      <MosaicWindow<ViewId>
        path={path}
        title={PANEL_TITLES[id]}
        createNode={() => 'library'}
        draggable={true}
        toolbarControls={
          <>
            <button
              key="expand"
              className="expand-button"
              onClick={() => handleExpand(id)}
              title={isExpanded ? "Restore" : "Expand"}
              style={{
                width: '24px',
                height: '24px',
                padding: 0,
                marginLeft: '4px',
                cursor: 'pointer',
                background: 'transparent',
                border: 'none',
                color: '#CCCCCC',
                fontSize: '16px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = '#4FC3F7';
                e.currentTarget.style.backgroundColor = 'rgba(79, 195, 247, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = '#CCCCCC';
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              ⛶
            </button>
            <button
              key="close"
              className="close-button"
              onClick={() => handleClose(id)}
              title="Close"
              style={{
                width: '24px',
                height: '24px',
                padding: 0,
                marginLeft: '4px',
                cursor: 'pointer',
                background: 'transparent',
                border: 'none',
                color: '#CCCCCC',
                fontSize: '20px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = '#FF6B6B';
                e.currentTarget.style.backgroundColor = 'rgba(255, 107, 107, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = '#CCCCCC';
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              ×
            </button>
          </>
        }
      >
        <div className="h-full overflow-auto">
          <Component />
        </div>
      </MosaicWindow>
    );
  };

  return (
    <AppProvider>
      <div className="h-screen flex flex-col bg-scian-darker">
      {/* Top Bar - iconik-inspired with glow */}
      <div className="h-14 bg-gradient-to-r from-scian-panel via-scian-dark to-scian-panel border-b border-scian-border flex items-center px-6 justify-between drag-region relative overflow-hidden">
        {/* Animated gradient background */}
        <div className="absolute inset-0 bg-gradient-to-r from-scian-cyan/5 via-scian-blue/5 to-scian-violet/5 opacity-50"></div>
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-scian-cyan/10 to-transparent animate-shimmer"></div>

        <div className="flex items-center gap-4 relative z-10">
          <div className="font-display font-bold text-2xl bg-gradient-to-r from-scian-cyan via-scian-blue to-scian-violet bg-clip-text text-transparent drop-shadow-lg animate-fadeIn">
            Scian
          </div>
          <div className="h-6 w-px bg-gradient-to-b from-transparent via-scian-border to-transparent"></div>
          <div className="text-scian-text-secondary text-sm font-medium">
            Turn creative chaos into visual clarity
          </div>
        </div>

        {/* Draggable Panel Icons */}
        <div className="flex items-center gap-2 relative z-10">
          {(Object.keys(PANEL_ICONS) as ViewId[]).map((viewId) => (
            <DraggablePanelIcon key={viewId} viewId={viewId} onAddPanel={handleAddPanel} />
          ))}
        </div>

        <div className="flex items-center gap-3 relative z-10">
          <button
            id="save-layout-btn"
            onClick={saveLayout}
            className="px-4 py-1.5 text-sm text-scian-text-primary rounded-lg hover:bg-scian-hover transition-all border border-transparent hover:border-scian-green/30 hover:shadow-lg hover:shadow-scian-green/20"
            title="Save current layout"
          >
            💾 Save Layout
          </button>
          <button className="px-4 py-1.5 text-sm text-scian-text-primary rounded-lg hover:bg-scian-hover transition-all border border-transparent hover:border-scian-cyan/30 hover:shadow-lg hover:shadow-scian-cyan/20">
            Settings
          </button>
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-scian-peach via-scian-violet to-scian-blue flex items-center justify-center text-sm font-semibold text-white ring-2 ring-scian-cyan/20 hover:ring-scian-cyan/40 transition-all cursor-pointer hover:scale-110 shadow-lg">
            U
          </div>
        </div>
      </div>

      {/* Mosaic Panel System */}
      <div className="flex-1 relative">
        <Mosaic<ViewId>
          renderTile={renderTile}
          value={currentNode}
          onChange={setCurrentNode}
          className="scian-mosaic"
          resize={{ minimumPaneSizePercentage: 10 }}
          zeroStateView={<div className="flex items-center justify-center h-full text-scian-text-muted">No panels available</div>}
        />
      </div>
    </div>
    </AppProvider>
  );
}

export default App;
