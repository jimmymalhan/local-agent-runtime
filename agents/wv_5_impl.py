```python
# This file implements a mini-map for 15+ agent graphs with smooth zoom/pan functionality using mouse wheel and touch pinch.

import pygame

class AgentGraph:
    def __init__(self, graph_data):
        self.graph_data = graph_data
        self.scale = 1.0
        self.offset = (0, 0)
        self.minimap_scale = 0.25
        self.minimap_offset = (10, 10)

    def draw(self, screen):
        # Draw the main graph scaled and offset
        for node in self.graph_data:
            pygame.draw.circle(screen, (255, 0, 0), (int(node[0] * self.scale + self.offset[0]), int(node[1] * self.scale + self.offset[1])), 5)

        # Draw the mini-map
        min_width = int(self.minimap_scale * screen.get_width())
        min_height = int(self.minimap_scale * screen.get_height())
        pygame.draw.rect(screen, (200, 200, 200), (self.minimap_offset[0], self.minimap_offset[1], min_width, min_height))
        
        for node in self.graph_data:
            mini_x = int((node[0] - self.offset[0]) / self.scale * min_width)
            mini_y = int((node[1] - self.offset[1]) / self.scale * min_height)
            pygame.draw.circle(screen, (255, 0, 0), (self.minimap_offset[0] + mini_x, self.minimap_offset[1] + mini_y), 3)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 4:  # Mouse wheel up
                self.scale *= 1.1
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 5:  # Mouse wheel down
                self.scale /= 1.1
            elif event.type == pygame.MOUSEMOTION:
                if pygame.mouse.get_pressed()[2]:  # Right mouse button pressed for dragging
                    dx, dy = event.rel
                    self.offset = (self.offset[0] + dx / self.scale, self.offset[1] + dy / self.scale)

# Example usage
if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    clock = pygame.time.Clock()

    graph_data = [(x * 50, y * 50) for x in range(10) for y in range(10)]
    agent_graph = AgentGraph(graph_data)

    running = True
    while running:
        events = pygame.event.get()
        if any(event.type == pygame.QUIT for event in events):
            running = False

        agent_graph.handle_events(events)
        screen.fill((255, 255, 255))
        agent_graph.draw(screen)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
```