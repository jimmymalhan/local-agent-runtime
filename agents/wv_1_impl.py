```python
# This file defines a React component for a canvas with SVG arrows connecting agent nodes.
# Clicking and dragging changes workflow routing.

import React, { useState } from 'react';

const WorkflowCanvas = () => {
  const [nodes, setNodes] = useState([]);
  const [arrows, setArrows] = useState([]);

  const addNode = (x, y) => {
    setNodes([...nodes, { id: nodes.length, x, y }]);
  };

  const connectNodes = (fromId, toId) => {
    setArrows([...arrows, { from: fromId, to: toId }]);
  };

  return (
    <div>
      <svg width="800" height="600">
        {nodes.map(node => (
          <circle
            key={node.id}
            cx={node.x}
            cy={node.y}
            r="10"
            fill="blue"
            onClick={() => addNode(node.x, node.y)}
          />
        ))}
        {arrows.map((arrow, index) => (
          <line
            key={index}
            x1={nodes.find(n => n.id === arrow.from).x}
            y1={nodes.find(n => n.id === arrow.from).y}
            x2={nodes.find(n => n.id === arrow.to).x}
            y2={nodes.find(n => n.id === arrow.to).y}
            stroke="black"
          />
        ))}
      </svg>
    </div>
  );
};

export default WorkflowCanvas;
```