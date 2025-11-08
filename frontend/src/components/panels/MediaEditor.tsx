import React, { useState } from 'react';
import TabPanel, { Tab } from '../common/TabPanel';
import { useApp } from '../../contexts/AppContext';

function AdjustTab() {
  const { selectedMedia } = useApp();
  const [brightness, setBrightness] = useState(100);
  const [contrast, setContrast] = useState(100);
  const [saturation, setSaturation] = useState(100);
  const [exposure, setExposure] = useState(0);

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Adjust</h2>
        <p className="text-scian-text-secondary text-sm">Fine-tune your media</p>
      </div>

      {/* Preview */}
      <div className="mb-6 bg-scian-panel rounded-lg border border-scian-border aspect-video flex items-center justify-center relative overflow-hidden group">
        {selectedMedia ? (
          <>
            <div className="absolute inset-0 bg-gradient-to-br from-scian-cyan/10 to-scian-blue/10"></div>
            <div className="text-center z-10">
              <div className="text-lg font-medium text-scian-text-primary mb-2">{selectedMedia.name}</div>
              <div className="text-sm text-scian-text-secondary">
                {selectedMedia.type === 'video' ? '🎬 Video' : '📷 Image'}
              </div>
              <div className="mt-4 px-4 py-2 bg-scian-cyan/20 backdrop-blur-sm rounded-lg text-sm text-scian-cyan border border-scian-cyan/30">
                Now editing: {selectedMedia.name}
              </div>
            </div>
          </>
        ) : (
          <div className="text-scian-text-muted text-sm">Select media from Library to edit</div>
        )}
      </div>

      {/* Adjustment controls */}
      <div className="space-y-4">
        <div>
          <div className="flex justify-between mb-2">
            <label className="text-sm text-scian-text-secondary">Brightness</label>
            <span className="text-sm text-scian-text-primary">{brightness}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="200"
            value={brightness}
            onChange={(e) => setBrightness(Number(e.target.value))}
            className="w-full accent-scian-cyan"
          />
        </div>

        <div>
          <div className="flex justify-between mb-2">
            <label className="text-sm text-scian-text-secondary">Contrast</label>
            <span className="text-sm text-scian-text-primary">{contrast}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="200"
            value={contrast}
            onChange={(e) => setContrast(Number(e.target.value))}
            className="w-full accent-scian-blue"
          />
        </div>

        <div>
          <div className="flex justify-between mb-2">
            <label className="text-sm text-scian-text-secondary">Saturation</label>
            <span className="text-sm text-scian-text-primary">{saturation}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="200"
            value={saturation}
            onChange={(e) => setSaturation(Number(e.target.value))}
            className="w-full accent-scian-violet"
          />
        </div>

        <div>
          <div className="flex justify-between mb-2">
            <label className="text-sm text-scian-text-secondary">Exposure</label>
            <span className="text-sm text-scian-text-primary">{exposure > 0 ? '+' : ''}{exposure}</span>
          </div>
          <input
            type="range"
            min="-100"
            max="100"
            value={exposure}
            onChange={(e) => setExposure(Number(e.target.value))}
            className="w-full accent-scian-peach"
          />
        </div>
      </div>

      <div className="mt-6 flex gap-2">
        <button className="flex-1 py-2 bg-scian-panel border border-scian-border rounded-lg text-sm text-scian-text-primary hover:bg-scian-hover">
          Reset
        </button>
        <button className="flex-1 py-2 bg-gradient-to-r from-scian-cyan to-scian-blue rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
          Apply
        </button>
      </div>
    </div>
  );
}

function FiltersTab() {
  const filters = [
    { name: 'Original', gradient: 'from-gray-500 to-gray-600' },
    { name: 'Vivid', gradient: 'from-pink-500 to-purple-500' },
    { name: 'Warm', gradient: 'from-orange-500 to-red-500' },
    { name: 'Cool', gradient: 'from-blue-500 to-cyan-500' },
    { name: 'B&W', gradient: 'from-gray-800 to-gray-400' },
    { name: 'Vintage', gradient: 'from-yellow-700 to-orange-800' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Filters</h2>
        <p className="text-scian-text-secondary text-sm">One-click styling</p>
      </div>

      {/* Preview */}
      <div className="mb-6 bg-scian-panel rounded-lg border border-scian-border aspect-video flex items-center justify-center">
        <div className="text-scian-text-muted text-sm">Media preview</div>
      </div>

      {/* Filter grid */}
      <div className="grid grid-cols-3 gap-3">
        {filters.map((filter) => (
          <button
            key={filter.name}
            className="bg-scian-panel border border-scian-border rounded-lg p-3 hover:border-scian-cyan transition-colors"
          >
            <div className={`aspect-square bg-gradient-to-br ${filter.gradient} rounded mb-2`} />
            <div className="text-xs text-scian-text-primary">{filter.name}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function CropTab() {
  const aspectRatios = [
    { name: '1:1', desc: 'Square', ratio: 'aspect-square' },
    { name: '4:5', desc: 'Portrait', ratio: 'aspect-[4/5]' },
    { name: '16:9', desc: 'Landscape', ratio: 'aspect-video' },
    { name: '9:16', desc: 'Story', ratio: 'aspect-[9/16]' },
  ];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Crop & Resize</h2>
        <p className="text-scian-text-secondary text-sm">Perfect for every platform</p>
      </div>

      {/* Preview */}
      <div className="mb-6 bg-scian-panel rounded-lg border border-scian-border aspect-video flex items-center justify-center">
        <div className="text-scian-text-muted text-sm">Media preview</div>
      </div>

      {/* Aspect ratios */}
      <div className="space-y-3 mb-6">
        <div className="text-sm text-scian-text-secondary mb-3">Aspect Ratios</div>
        {aspectRatios.map((ratio) => (
          <button
            key={ratio.name}
            className="w-full flex items-center justify-between bg-scian-panel border border-scian-border rounded-lg p-3 hover:border-scian-blue transition-colors"
          >
            <div>
              <div className="text-sm text-scian-text-primary font-medium">{ratio.name}</div>
              <div className="text-xs text-scian-text-secondary">{ratio.desc}</div>
            </div>
            <div className={`w-12 ${ratio.ratio} bg-scian-border rounded`} />
          </button>
        ))}
      </div>

      <button className="w-full py-2 bg-gradient-to-r from-scian-blue to-scian-violet rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
        Apply Crop
      </button>
    </div>
  );
}

function TextTab() {
  const [text, setText] = useState('');
  const [fontSize, setFontSize] = useState(32);

  const fonts = ['Inter', 'Roboto', 'Playfair', 'Bebas', 'Dancing Script'];
  const colors = ['#FFFFFF', '#000000', '#4FC3F7', '#FF9E80', '#AB47BC', '#66BB6A'];

  return (
    <div className="p-6 bg-scian-dark h-full">
      <div className="mb-4">
        <h2 className="text-2xl font-display font-semibold mb-2 text-scian-text-primary">Add Text</h2>
        <p className="text-scian-text-secondary text-sm">Overlay text on your media</p>
      </div>

      {/* Preview */}
      <div className="mb-6 bg-scian-panel rounded-lg border border-scian-border aspect-video flex items-center justify-center">
        <div className="text-scian-text-muted text-sm">Media preview</div>
      </div>

      {/* Text input */}
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Enter your text..."
        className="w-full mb-4 bg-scian-darker border border-scian-border rounded-lg px-4 py-2 text-scian-text-primary placeholder-scian-text-muted focus:border-scian-cyan focus:outline-none"
      />

      {/* Font size */}
      <div className="mb-4">
        <div className="flex justify-between mb-2">
          <label className="text-sm text-scian-text-secondary">Font Size</label>
          <span className="text-sm text-scian-text-primary">{fontSize}px</span>
        </div>
        <input
          type="range"
          min="12"
          max="72"
          value={fontSize}
          onChange={(e) => setFontSize(Number(e.target.value))}
          className="w-full accent-scian-cyan"
        />
      </div>

      {/* Font family */}
      <div className="mb-4">
        <div className="text-sm text-scian-text-secondary mb-2">Font</div>
        <div className="flex gap-2 flex-wrap">
          {fonts.map((font) => (
            <button
              key={font}
              className="px-3 py-1 bg-scian-panel border border-scian-border rounded text-xs text-scian-text-primary hover:border-scian-cyan"
              style={{ fontFamily: font }}
            >
              {font}
            </button>
          ))}
        </div>
      </div>

      {/* Color picker */}
      <div className="mb-4">
        <div className="text-sm text-scian-text-secondary mb-2">Color</div>
        <div className="flex gap-2">
          {colors.map((color) => (
            <button
              key={color}
              className="w-8 h-8 rounded border-2 border-scian-border hover:border-scian-cyan"
              style={{ backgroundColor: color }}
            />
          ))}
        </div>
      </div>

      <button className="w-full py-2 bg-gradient-to-r from-scian-violet to-scian-peach rounded-lg text-sm font-medium text-white hover:opacity-90 transition-opacity shadow-lg">
        Add Text
      </button>
    </div>
  );
}

export default function MediaEditor() {
  const tabs: Tab[] = [
    {
      id: 'adjust',
      label: 'Adjust',
      content: <AdjustTab />,
    },
    {
      id: 'filters',
      label: 'Filters',
      content: <FiltersTab />,
    },
    {
      id: 'crop',
      label: 'Crop',
      content: <CropTab />,
    },
    {
      id: 'text',
      label: 'Text',
      content: <TextTab />,
    },
  ];

  return <TabPanel tabs={tabs} defaultTab="adjust" />;
}
