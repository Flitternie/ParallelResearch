import json
from typing import Dict, List, Any, Optional, TypedDict
from datetime import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field

from research_visualizer import BaseResearchVisualizer

@dataclass
class VisualizationConfig:
    """Configuration options for the visualization"""
    # Network dimensions
    width: str = "100%"
    height: int = 800
    
    # Node appearance
    node_size: int = 30
    node_font_size: int = 14
    node_border_width: int = 2
    node_shape: str = "dot"
    
    # Edge appearance
    edge_width: int = 2
    edge_smooth_type: str = "continuous"
    
    # Physics settings
    physics_enabled: bool = True
    gravitational_constant: int = -80000
    spring_constant: float = 0.001
    spring_length: int = 200
    
    # Layout settings
    layout_direction: str = "UD"  # UD = Up-Down, LR = Left-Right
    layout_sort_method: str = "directed"
    level_separation: int = 150
    
    # Info panel settings
    info_panel_width: int = 400
    info_panel_position: Dict[str, str] = field(default_factory=lambda: {"right": "20px", "top": "20px"})
    
    # Colors
    status_colors: Dict[str, str] = field(default_factory=lambda: {
        "started": "#ADD8E6",
        "completed": "#90EE90",
        "error": "#F08080",
        "default": "#D3D3D3",
    })
    
    # Operation colors
    operation_colors: Dict[str, str] = field(default_factory=lambda: {
        "plan": "#90EE90",  # Green for plan operations
        "research": "#FF0000",  # Red for research operations
        "agent_selection": "#87CEEB",  # Sky blue for agent selection
        "search_planning": "#FFA500",  # Orange for search planning
        "subquery_execution": "#DDA0DD",  # Plum for subquery execution
        "default": "#D3D3D3"  # Default gray
    })


class HTMLTemplates:
    """HTML templates for visualization components"""
    @staticmethod
    def get_base_template() -> str:
        return '''<!DOCTYPE html>
<html>
<head>
    <title>Research Process Visualization</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css" rel="stylesheet" type="text/css" />
    {styles}
</head>
<body>
    <div id="mynetwork"></div>
    <div id="click-info"></div>
    {scripts}
</body>
</html>'''

    @staticmethod
    def get_styles(config: VisualizationConfig) -> str:
        return f'''<style type="text/css">
        #mynetwork {{
            width: {config.width};
            height: {config.height}px;
            border: 1px solid lightgray;
        }}
        #click-info {{
            display: none;
            position: fixed;
            right: {config.info_panel_position["right"]};
            top: {config.info_panel_position["top"]};
            width: {config.info_panel_width}px;
            max-height: 80vh;
            overflow-y: auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            transition: all 0.3s ease;
        }}
    </style>'''

    @staticmethod
    def get_network_options(config: VisualizationConfig) -> Dict[str, Any]:
        return {
            "nodes": {
                "size": config.node_size,
                "font": {
                    "size": config.node_font_size
                }
            },
            "edges": {
                "width": config.edge_width,
                "smooth": {
                    "type": config.edge_smooth_type
                }
            },
            "physics": {
                "enabled": config.physics_enabled,
                "barnesHut": {
                    "gravitationalConstant": config.gravitational_constant,
                    "springConstant": config.spring_constant,
                    "springLength": config.spring_length
                }
            },
            "layout": {
                "hierarchical": {
                    "direction": config.layout_direction,
                    "sortMethod": config.layout_sort_method,
                    "levelSeparation": config.level_separation
                }
            }
        }


class ResearchVisualizer(BaseResearchVisualizer):
    def __init__(self, log_file: str = "research_progress.json", config: Optional[VisualizationConfig] = None):
        self.log_file = log_file
        self.config = config or VisualizationConfig()
        self.templates = HTMLTemplates()

    def _create_hover_info(self, node: Dict[str, Any]) -> str:
        """Create hover information for a node"""
        return self._clean_text(node['query'])

    def _create_click_info(self, node: Dict[str, Any]) -> str:
        """Create detailed click information for a node"""
        details_html = f'''
<div style="position: relative;">
    <button onclick="this.parentElement.parentElement.style.display='none'" style="position: absolute; right: 0; top: 0; border: none; background: none; cursor: pointer; font-size: 20px;">×</button>
    <h3>Query {node['id']} Details</h3>
    <div style="margin-bottom: 15px;">
        <b>Status:</b> <span style="color: {self.config.status_colors.get(node['status'], self.config.status_colors['default'])}">{node['status'].upper()}</span><br>
        <b>Depth:</b> {node['depth']}<br>'''

        if node.get("operation"):
            details_html += f'        <b>Operation:</b> {node["operation"].replace("_", " ").title()}<br>'

        if node.get("concurrent_group"):
            details_html += f'        <b>Concurrent Group:</b> {node["concurrent_group"]}<br>'
            
        if node.get("start_time"):
            start_time = datetime.fromisoformat(node["start_time"]).strftime("%Y-%m-%d %H:%M:%S")
            details_html += f'        <b>Start Time:</b> {start_time}<br>'
            
        if node.get("duration"):
            details_html += f'        <b>Duration:</b> {node["duration"]}<br>'

        # Handle special operations
        if node.get("operation") == "agent_selection" and node.get("results"):
            details_html += self._format_agent_selection_html(node["results"])
        elif node.get("operation") == "search_planning" and node.get("results"):
            details_html += self._format_search_planning_html(node["results"])
        elif node.get("operation") == "subquery_execution" and node.get("results"):
            details_html += self._format_subquery_execution_html(node["results"], node)
        elif node.get("operation") == "plan":
            # Handle plan operations with special query parsing
            query = self._clean_text(node['query'])
            
            if "Initial Query:" in query:
                parsed_query = self._parse_initial_query(query)
                details_html += self._format_initial_query_html(parsed_query)
            elif "Previous research goal:" in query:
                parsed_query = self._parse_research_goal(query)
                details_html += self._format_research_goal_html(parsed_query)
            else:
                details_html += f'''
        <b>Query:</b>
        <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{query}</div>
'''
            
            # Add results formatting for plan operations
            if node.get("results"):
                details_html += self._format_results_html(node["results"])
        else:
            # Handle regular queries
            query = self._clean_text(node['query'])
            
            if "Initial Query:" in query:
                parsed_query = self._parse_initial_query(query)
                details_html += self._format_initial_query_html(parsed_query)
            elif "Previous research goal:" in query:
                parsed_query = self._parse_research_goal(query)
                details_html += self._format_research_goal_html(parsed_query)
            else:
                details_html += f'''
        <b>Query:</b>
        <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{query}</div>
'''

        if node.get("results") and node.get("operation") not in ["agent_selection", "search_planning", "subquery_execution", "plan"]:
            details_html += self._format_results_html(node["results"])

        details_html += '''
    </div>
</div>
'''
        return f'''
var clickInfo = document.getElementById('click-info');
if (!clickInfo) {{
    clickInfo = document.createElement('div');
    clickInfo.id = 'click-info';
    clickInfo.style.cssText = 'position: fixed; right: {self.config.info_panel_position["right"]}; top: {self.config.info_panel_position["top"]}; width: {self.config.info_panel_width}px; max-height: 80vh; overflow-y: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 2px 2px 10px rgba(0,0,0,0.2); z-index: 1000;';
    document.body.appendChild(clickInfo);
}}
clickInfo.innerHTML = `{details_html}`;
'''

    def _create_network_script(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        """Create the JavaScript code for network initialization"""
        options = self.templates.get_network_options(self.config)
        script = f"""
<script type=\"text/javascript\">
var nodes = new vis.DataSet({json.dumps(nodes)});
var edges = new vis.DataSet({json.dumps(edges)});
var container = document.getElementById('mynetwork');
var data = {{ nodes: nodes, edges: edges }};
var options = {json.dumps(options)};
var network = new vis.Network(container, data, options);

network.on('click', function(params) {{
    if (params.nodes.length > 0) {{
        var nodeId = params.nodes[0];
        var node = nodes.get(nodeId);
        
        // Show click info if available
        if (node.clickInfo) {{
            eval(node.clickInfo);
            document.getElementById('click-info').style.display = 'block';
        }}
    }}
}});
</script>
"""
        return script

    def visualize(self, output_file: str = "research_visualization.html"):
        """Create an interactive tree visualization of the research progress"""
        log_data = self.load_log()
        
        # Create nodes list - filter out internal nodes
        nodes = []
        
        for node in log_data["nodes"]:
            # Skip internal nodes (nodes with IDs like X.X or X.X.X)
            if self._is_internal_node(node["id"]):
                continue
                
            # First check for operation-based color
            background_color = self.config.operation_colors.get(
                node.get("operation", "default"),
                self.config.operation_colors["default"]
            )
            
            # If no operation color found, fall back to status-based coloring
            if background_color == self.config.operation_colors["default"]:
                background_color = self.config.status_colors.get(
                    node["status"], 
                    self.config.status_colors["default"]
                )
            
            node_data = {
                "id": node["id"],
                "label": f"Q{node['id']}",
                "title": self._clean_text(node["query"]),
                "color": background_color,
                "clickInfo": self._create_click_info(node),
                "borderWidth": self.config.node_border_width,
                "shape": self.config.node_shape
            }
            
            nodes.append(node_data)
        
        # Create edges list - filter out edges involving internal nodes
        edges = []
        for edge in log_data["edges"]:
            # Skip edges that involve internal nodes
            if self._is_internal_node(edge["from"]) or self._is_internal_node(edge["to"]):
                continue
            edges.append({"from": edge["from"], "to": edge["to"], "arrows": "to"})
        
        # Generate HTML content
        html_content = self.templates.get_base_template().format(
            styles=self.templates.get_styles(self.config),
            scripts=self._create_network_script(nodes, edges)
        )
        
        # Save visualization
        with open(output_file, 'w') as f:
            f.write(html_content)


class AnimatedResearchVisualizer(ResearchVisualizer):
    def __init__(self, log_file: str = "research_progress.json", config: Optional[VisualizationConfig] = None):
        if config is None:
            config = VisualizationConfig()
            # Disable physics and adjust layout for stability
            config.physics_enabled = False
            config.layout_direction = "UD"
            # config.layout_sort_method = "directed"
            # config.level_separation = 200
        super().__init__(log_file, config)
        self.animation_speed = 1000  # milliseconds between node appearances (increased from 1000)
    
    def _create_animation_script(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        """Create the JavaScript code for animated network initialization"""
        options = self.templates.get_network_options(self.config)
        
        # Group nodes by start time and concurrent group
        time_groups = defaultdict(list)
        concurrent_groups = defaultdict(list)
        
        for node in nodes:
            start_time = node.get('start_time', '')
            concurrent_group = node.get('concurrent_group')
            
            if concurrent_group is not None:
                # Group by concurrent_group first, then by start_time
                concurrent_groups[concurrent_group].append(node)
            else:
                # Node without concurrent group gets its own group
                key = (start_time,)
                time_groups[key].append(node)
        
        # Add concurrent groups to time groups
        for concurrent_group, group_nodes in concurrent_groups.items():
            # Use the earliest start_time in the group as the key
            earliest_time = min(node.get('start_time', '') for node in group_nodes)
            key = (earliest_time, concurrent_group)
            time_groups[key].extend(group_nodes)
        
        # Sort time groups by start time
        sorted_groups = sorted(time_groups.items(), key=lambda x: x[0][0])
        
        # Debug output
        print("DEBUG: Grouping results:")
        for i, (key, group) in enumerate(sorted_groups):
            node_ids = [node['id'] for node in group]
            print(f"  Group {i}: {key} -> Nodes: {node_ids}")
        
        # Flatten the groups into a list of node groups
        node_groups = [group for _, group in sorted_groups]
        
        # Convert node groups to JSON string
        node_groups_json = json.dumps(node_groups)
        
        return f'''<script type="text/javascript">
        var nodes = new vis.DataSet([]);
        var edges = new vis.DataSet([]);

        var container = document.getElementById('mynetwork');
        var data = {{
            nodes: nodes,
            edges: edges
        }};
        var options = {json.dumps(options, indent=8)};
        var network = new vis.Network(container, data, options);
        
        // Animation control
        var animationSpeed = {self.animation_speed};
        var nodeGroups = {node_groups_json};
        var edgeQueue = {json.dumps(edges)};
        var currentGroupIndex = 0;
        var animationInterval;
        var visibleNodes = new Set();
        
        // Add play/pause button
        var controlDiv = document.createElement('div');
        controlDiv.style.position = 'absolute';
        controlDiv.style.top = '10px';
        controlDiv.style.left = '10px';
        controlDiv.style.zIndex = '1000';
        controlDiv.style.background = 'white';
        controlDiv.style.padding = '10px';
        controlDiv.style.borderRadius = '5px';
        controlDiv.style.boxShadow = '0 2px 5px rgba(0,0,0,0.2)';
        
        var playButton = document.createElement('button');
        playButton.innerHTML = '▶ Play';
        playButton.style.marginRight = '10px';
        playButton.onclick = function() {{
            if (animationInterval) {{
                clearInterval(animationInterval);
                animationInterval = null;
                playButton.innerHTML = '▶ Play';
            }} else {{
                startAnimation();
                playButton.innerHTML = '⏸ Pause';
            }}
        }};
        
        var resetButton = document.createElement('button');
        resetButton.innerHTML = '↺ Reset';
        resetButton.onclick = function() {{
            resetAnimation();
        }};
        
        controlDiv.appendChild(playButton);
        controlDiv.appendChild(resetButton);
        container.parentElement.appendChild(controlDiv);
        
        function addEdgesForVisibleNodes() {{
            console.log('Checking edges for visible nodes:', Array.from(visibleNodes));
            // Check all edges to see if both source and target nodes are now visible
            edgeQueue.forEach(function(edge) {{
                if (visibleNodes.has(edge.from) && visibleNodes.has(edge.to)) {{
                    // Check if edge is not already added
                    var existingEdge = edges.get(edge.id || edge.from + '-' + edge.to);
                    if (!existingEdge) {{
                        console.log('Adding edge:', edge.from, '->', edge.to);
                        edges.add(edge);
                    }}
                }}
            }});
        }}
        
        function startAnimation() {{
            console.log('Starting animation with', nodeGroups.length, 'groups');
            animationInterval = setInterval(function() {{
                try {{
                    if (currentGroupIndex < nodeGroups.length) {{
                        // Add all nodes in the current group
                        var currentGroup = nodeGroups[currentGroupIndex];
                        console.log('Adding group', currentGroupIndex, 'with nodes:', currentGroup.map(function(n) {{ return n.id; }}));
                        currentGroup.forEach(function(node) {{
                            console.log('Adding node:', node.id);
                            nodes.add(node);
                            visibleNodes.add(node.id);
                        }});
                        
                        // Add edges that can now be displayed
                        console.log('Adding edges for group', currentGroupIndex);
                        addEdgesForVisibleNodes();

                        if (currentGroupIndex == 0) {{
                            // Fit the network to the visible nodes
                            network.fit({{animation: {{duration: 500, easingFunction: 'easeInOutQuad'}}}});
                        }}
                        
                        currentGroupIndex++;
                        console.log('Moved to group index:', currentGroupIndex);
                    }} else {{
                        clearInterval(animationInterval);
                        animationInterval = null;
                        playButton.innerHTML = '▶ Play';
                        console.log('Animation completed');
                    }}
                }} catch (error) {{
                    console.error('Error in animation:', error);
                    clearInterval(animationInterval);
                    animationInterval = null;
                    playButton.innerHTML = '▶ Play';
                }}
            }}, animationSpeed);
        }}
        
        function resetAnimation() {{
            if (animationInterval) {{
                clearInterval(animationInterval);
                animationInterval = null;
            }}
            nodes.clear();
            edges.clear();
            visibleNodes.clear();
            currentGroupIndex = 0;
            playButton.innerHTML = '▶ Play';
        }}
        
        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                var nodeId = params.nodes[0];
                var node = nodes.get(nodeId);
                if (node.clickInfo) {{
                    eval(node.clickInfo);
                    document.getElementById('click-info').style.display = 'block';
                }}
            }}
        }});
    </script>'''

    def visualize(self, output_file: str = "animated_research_visualization.html"):
        """Create an animated interactive tree visualization of the research progress"""
        log_data = self.load_log()
        
        # Create nodes list
        nodes = []
        for node in log_data["nodes"]:
            # Skip nodes with "X.X" pattern in their ID
            if "." in str(node["id"]):
                continue
                
            # First check for operation-based color
            background_color = self.config.operation_colors.get(
                node.get("operation", "default"),
                self.config.operation_colors["default"]
            )
            
            # If no operation color found, fall back to status-based coloring
            if background_color == self.config.operation_colors["default"]:
                background_color = self.config.status_colors.get(
                    node["status"], 
                    self.config.status_colors["default"]
                )
            
            nodes.append({
                "id": node["id"],
                "label": f"Q{node['id']}",
                "title": self._clean_text(node["query"]),
                "color": background_color,
                "clickInfo": self._create_click_info(node),
                "borderWidth": self.config.node_border_width,
                "shape": self.config.node_shape,
                "start_time": node.get("start_time", ""),
                "concurrent_group": node.get("concurrent_group")
            })
        
        # Create edges list - only include edges where both nodes are not skipped
        visible_node_ids = {node["id"] for node in nodes}
        edges = [
            {
                "id": f"{edge['from']}-{edge['to']}", 
                "from": edge["from"], 
                "to": edge["to"], 
                "arrows": "to"
            }
            for edge in log_data["edges"]
            if edge["from"] in visible_node_ids and edge["to"] in visible_node_ids
        ]
        
        # Generate HTML content
        html_content = self.templates.get_base_template().format(
            styles=self.templates.get_styles(self.config),
            scripts=self._create_animation_script(nodes, edges)
        )
        
        # Save visualization
        with open(output_file, 'w') as f:
            f.write(html_content)
