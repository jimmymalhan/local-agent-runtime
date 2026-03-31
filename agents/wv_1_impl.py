```python
# This file defines a React component for a canvas with SVG arrows connecting agent nodes.
# Clicking and dragging changes workflow routing.

import React, { useState } from 'react';

const WorkflowCanvas = () => {
  const [nodes, setNodes] = useState([]);
  const [arrows, setArrows] = useState([]);

  const addNode = (x, y) => {
    setNodes([...nodes, { id: Date.now(), x, y }]);
  };

  const connectNodes = (fromNodeId, toNodeId) => {
    setArrows([...arrows, { from: fromNodeId, to: toNodeId }]);
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '600px' }}>
      <svg width="100%" height="100%">
        {arrows.map((arrow) => (
          <line
            key={arrow.from + '-' + arrow.to}
            x1={nodes.find(node => node.id === arrow.from).x}
            y1={nodes.find(node => node.id === arrow.from).y}
            x2={nodes.find(node => node.id === arrow.to).x}
            y2={nodes.find(node => node.id === arrow.to).y}
            stroke="black"
          />
        ))}
      </svg>
      <div
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          cursor: 'crosshair',
        }}
        onClick={(e) => addNode(e.clientX, e.clientY)}
      >
        {/* Nodes will be rendered here dynamically */}
      </div>
    </div>
  );
};

export default WorkflowCanvas;
```