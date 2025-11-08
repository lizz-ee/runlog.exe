import React, { createContext, useContext, useState, ReactNode } from 'react';

// Types for our shared state
interface Post {
  id: string;
  platform: 'instagram' | 'facebook' | 'twitter' | 'tiktok';
  caption: string;
  imageUrl?: string;
  username: string;
  likes: number;
  comments: number;
}

interface Media {
  id: string;
  type: 'image' | 'video';
  url: string;
  thumbnail?: string;
}

interface Message {
  id: string;
  platform: string;
  author: string;
  content: string;
  postId?: string;
}

interface Draft {
  caption: string;
  platform: 'instagram' | 'facebook' | 'twitter' | 'tiktok';
}

interface AppState {
  // Currently selected/active items
  selectedPost: Post | null;
  selectedMedia: Media | null;
  selectedMessage: Message | null;
  currentDraft: Draft | null;

  // Actions to update state
  setSelectedPost: (post: Post | null) => void;
  setSelectedMedia: (media: Media | null) => void;
  setSelectedMessage: (message: Message | null) => void;
  setCurrentDraft: (draft: Draft | null) => void;

  // Panel focus actions
  focusPanel: (panelId: string) => void;
  activePanelId: string | null;
}

const AppContext = createContext<AppState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [selectedMedia, setSelectedMedia] = useState<Media | null>(null);
  const [selectedMessage, setSelectedMessage] = useState<Message | null>(null);
  const [currentDraft, setCurrentDraft] = useState<Draft | null>(null);
  const [activePanelId, setActivePanelId] = useState<string | null>(null);

  const focusPanel = (panelId: string) => {
    setActivePanelId(panelId);
    // Emit event for panel to respond
    window.dispatchEvent(new CustomEvent('focusPanel', { detail: { panelId } }));
  };

  return (
    <AppContext.Provider
      value={{
        selectedPost,
        selectedMedia,
        selectedMessage,
        currentDraft,
        setSelectedPost,
        setSelectedMedia,
        setSelectedMessage,
        setCurrentDraft,
        focusPanel,
        activePanelId,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
