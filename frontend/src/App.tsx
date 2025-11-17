import { useState, useEffect } from 'react';
import { projectsApi } from './lib/api';
import type { Project, Shot } from './lib/types';
import Dashboard from './components/Dashboard';
import ProjectView from './components/ProjectView';
import ShotView from './components/ShotView';
import './App.css';

type View =
  | { type: 'dashboard' }
  | { type: 'project'; project: Project }
  | { type: 'shot'; shot: Shot; project: Project };

function App() {
  const [currentView, setCurrentView] = useState<View>({ type: 'dashboard' });
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = async () => {
    try {
      const response = await projectsApi.list();
      setProjects(response.data);
    } catch (error) {
      console.error('Failed to load projects:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleProjectSelect = (project: Project) => {
    setCurrentView({ type: 'project', project });
  };

  const handleShotSelect = (shot: Shot, project: Project) => {
    setCurrentView({ type: 'shot', shot, project });
  };

  const handleBackToDashboard = () => {
    setCurrentView({ type: 'dashboard' });
    loadProjects();
  };

  const handleBackToProject = () => {
    if (currentView.type === 'shot') {
      setCurrentView({ type: 'project', project: currentView.project });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900 text-white">
        <div className="text-xl">Loading Scian Flow...</div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-900 text-white flex flex-col">
      {/* Top bar */}
      <div className="bg-gray-800 border-b border-gray-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <h1 className="text-2xl font-bold text-blue-400">Scian Flow</h1>
          {currentView.type !== 'dashboard' && (
            <button
              onClick={handleBackToDashboard}
              className="text-gray-400 hover:text-white transition-colors"
            >
              ← Dashboard
            </button>
          )}
          {currentView.type === 'shot' && (
            <>
              <span className="text-gray-600">/</span>
              <button
                onClick={handleBackToProject}
                className="text-gray-400 hover:text-white transition-colors"
              >
                {currentView.project.name}
              </button>
            </>
          )}
        </div>
        <div className="text-sm text-gray-400">
          Production Tracking System
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        {currentView.type === 'dashboard' && (
          <Dashboard
            projects={projects}
            onProjectSelect={handleProjectSelect}
            onProjectsChange={loadProjects}
          />
        )}
        {currentView.type === 'project' && (
          <ProjectView
            project={currentView.project}
            onShotSelect={(shot) => handleShotSelect(shot, currentView.project)}
          />
        )}
        {currentView.type === 'shot' && (
          <ShotView shot={currentView.shot} />
        )}
      </div>
    </div>
  );
}

export default App;
