import React, { useState } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';

function ChatTab() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hey, I\'m Scian 👋 — let\'s make your creative life easier. How can I help you today?' }
  ]);
  const [input, setInput] = useState('');

  const sendMessage = () => {
    if (!input.trim()) return;

    setMessages([...messages, { role: 'user', content: input }]);
    setInput('');

    // TODO: Connect to backend AI service
    setTimeout(() => {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'AI response coming soon! Connect to backend API.'
      }]);
    }, 1000);
  };

  return (
    <div className="h-full flex flex-col p-6 bg-scian-dark">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">AI Assistant</h2>
        <p className="text-scian-text-secondary text-sm">Your creative companion</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto mb-4 space-y-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-3 ${
                msg.role === 'user'
                  ? 'bg-gradient-to-r from-scian-cyan to-scian-blue text-white shadow-lg'
                  : 'bg-scian-panel text-scian-text-primary border border-scian-border'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
          placeholder="Ask me anything..."
          className="flex-1 bg-scian-darker border border-scian-border rounded-lg px-4 py-2 text-scian-text-primary placeholder-scian-text-muted focus:border-scian-cyan focus:outline-none"
        />
        <button
          onClick={sendMessage}
          className="px-6 py-2 bg-gradient-to-r from-scian-cyan to-scian-blue rounded-lg font-medium text-white hover:opacity-90 transition-opacity shadow-lg"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function HistoryTab() {
  const conversations = [
    { id: 1, title: 'Caption ideas for product launch', date: '2 hours ago', preview: 'Help me write a caption for...' },
    { id: 2, title: 'Best posting times', date: 'Yesterday', preview: 'When should I post on Instagram...' },
    { id: 3, title: 'Hashtag suggestions', date: '2 days ago', preview: 'Suggest hashtags for travel content...' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Chat History</h2>
        <p className="text-scian-text-secondary text-sm">Previous conversations</p>
      </div>

      <div className="space-y-3">
        {conversations.map((conv, i) => (
          <div
            key={conv.id}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-cyan transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-cyan/20 cursor-pointer animate-fadeIn"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-scian-text-primary font-medium">{conv.title}</h3>
              <span className="text-xs text-scian-text-muted">{conv.date}</span>
            </div>
            <p className="text-sm text-scian-text-secondary">{conv.preview}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function TemplatesTab() {
  const { setCurrentDraft, focusPanel } = useApp();

  const templates = [
    { id: 1, name: 'Product Launch', emoji: '🚀', description: 'Generate captions for product announcements', sampleCaption: '🚀 Exciting news! We\'re thrilled to announce our latest product launch. This game-changing innovation is designed to revolutionize the way you work. Stay tuned for more details! #ProductLaunch #Innovation #NewRelease' },
    { id: 2, name: 'Engagement Boost', emoji: '💬', description: 'Create posts that drive conversations', sampleCaption: '💬 Quick question for our amazing community: What\'s your biggest challenge this week? Drop a comment below and let\'s support each other! Your insights matter to us. #CommunityFirst #LetsTalk #Engagement' },
    { id: 3, name: 'Story Ideas', emoji: '✨', description: 'Get creative story concepts', sampleCaption: '✨ Behind the scenes magic ✨ Swipe to see how we bring your favorite products to life! From concept to creation, every detail matters. Which stage is your favorite? #BehindTheScenes #CreativeProcess #StoryTime' },
    { id: 4, name: 'Hashtag Strategy', emoji: '#️⃣', description: 'Build effective hashtag sets', sampleCaption: 'Building your brand presence starts with the right hashtags! 📊 Here are our top performers this month: #BrandBuilding #SocialMediaTips #ContentStrategy #DigitalMarketing #GrowthHacking #MarketingGoals' },
  ];

  const handleTemplateClick = (template: typeof templates[0]) => {
    // Set the draft with AI-generated content
    setCurrentDraft({
      caption: template.sampleCaption,
      platform: 'instagram'
    });
    // Switch to Post Editor
    focusPanel('editor');
  };

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">AI Templates</h2>
        <p className="text-scian-text-secondary text-sm">Quick-start prompts</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {templates.map((template, i) => (
          <div
            key={template.id}
            onClick={() => handleTemplateClick(template)}
            className="bg-scian-panel border border-scian-border rounded-lg p-4 hover:border-scian-violet transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-scian-violet/20 cursor-pointer animate-fadeIn"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            <div className="text-3xl mb-2">{template.emoji}</div>
            <h3 className="text-scian-text-primary font-medium mb-1">{template.name}</h3>
            <p className="text-xs text-scian-text-secondary">{template.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AIAssistant() {
  const tabs: Tab[] = [
    {
      id: 'chat',
      label: 'Chat',
      content: <ChatTab />,
    },
    {
      id: 'history',
      label: 'History',
      content: <HistoryTab />,
    },
    {
      id: 'templates',
      label: 'Templates',
      content: <TemplatesTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="chat" />;
}
