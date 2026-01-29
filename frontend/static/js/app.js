/**
 * Deep Research Frontend Application
 * Main application logic for chat interface and research management
 */

class DeepResearchApp {
    constructor() {
        this.socket = io();
        this.currentSessionId = null;
        this.isResearching = false;
        this.visualizer = null;
        this.loadingInterval = null;
        this.lastStatusMessageElement = null; // Track the last status message for updates
        this.lastReportContent = null; // Store the last report content for downloading
        this.visualizationUpdateTimeout = null; // Debounce visualization updates
        this.previousNodes = new Map(); // Track previous node states for termination detection
        this.notificationStack = []; // Track active notifications for stacking
        
        this.initializeElements();
        this.setupEventListeners();
        this.setupSocketListeners();
        this.setupResizer();
        this.initializeVisualization();
    }

    initializeElements() {
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.chatMessages = document.getElementById('chatMessages');
        // Progress elements removed, set to null to avoid errors
        this.progressContainer = null;
        this.progressFill = null;
        this.progressText = null;
        this.vizContent = document.getElementById('vizContent');
        this.infoPanel = document.getElementById('infoPanel');
        this.infoPanelContent = document.getElementById('infoPanelContent');
    }

    setupEventListeners() {
        // Chat input events
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

                // Visualization control events
        document.getElementById('centerBtn').addEventListener('click', () => {
            if (window.resetZoom) {
                window.resetZoom();
            } else {
                console.log('Center view functionality not available');
            }
        }); 
        
        document.getElementById('expandBtn').addEventListener('click', () => {
            if (window.expandAll) {
                window.expandAll();
            } else {
                console.log('Expand all functionality not available');
            }
        });
        
        document.getElementById('collapseBtn').addEventListener('click', () => {
            if (window.collapseAll) {
                window.collapseAll();
            } else {
                console.log('Collapse all functionality not available');
            }
        });
        
        document.getElementById('closePanelBtn').addEventListener('click', () => {
            this.closeInfoPanel();
        });

                // Window resize handler
        window.addEventListener('resize', () => {
            // The new visualizer handles resize automatically through D3
            console.log('Window resized - visualization will auto-adjust');
        });

        // Node click handler for visualization
        document.getElementById('vizContent').addEventListener('nodeClick', (event) => {
            this.showNodeInfo(event.detail.nodeData);
        });
    }

    setupSocketListeners() {
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.addStatusMessage('info', 'Connected to research server');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.addStatusMessage('error', 'Disconnected from server');
        });

        this.socket.on('status_update', (data) => {
            this.updateStatus(data.message);
            
            // Transition from research running to loading state when processing begins
            const researchRunningViz = document.getElementById('researchRunningViz');
            if (researchRunningViz && researchRunningViz.style.display === 'flex') {
                // Check if the status indicates research is actually processing
                if (data.message && (
                    data.message.includes('Generating') || 
                    data.message.includes('Research started') ||
                    data.message.includes('Processing') ||
                    data.message.includes('Building')
                )) {
                    this.showLoadingState();
                }
            }
        });

        this.socket.on('progress_update', (data) => {
            this.updateProgress(data.progress);
            
            // Ensure we're in loading state when progress updates come in
            const researchRunningViz = document.getElementById('researchRunningViz');
            if (researchRunningViz && researchRunningViz.style.display === 'flex') {
                this.showLoadingState();
            }
        });

        this.socket.on('visualization_update', (data) => {
            console.log('Visualization update received:', data);
            // Validate data structure before passing to updateVisualization
            const nodes = data && data.nodes ? data.nodes : [];
            const edges = data && data.edges ? data.edges : [];
            
            // Check for terminated nodes and show notifications
            this.checkForTerminatedNodes(nodes);
            
            this.updateVisualization(nodes, edges);
        });

        this.socket.on('status_notification', (data) => {
            console.log('Status notification received:', data);
            // Add notification to chat
            this.addStatusMessage(data.type || 'info', data.message);
        });

        this.socket.on('research_complete', (data) => {
            this.onResearchComplete(data);
        });

        this.socket.on('research_error', (data) => {
            this.onResearchError(data);
        });
    }

    setupResizer() {
        const resizer = document.getElementById('resizer');
        const chatPanel = document.getElementById('chatPanel');
        const vizPanel = document.getElementById('vizPanel');
        let isResizing = false;

        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            const container = document.querySelector('.container');
            container.classList.add('resizing');
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            e.preventDefault();
        });

        const handleMouseMove = (e) => {
            if (!isResizing) return;
            
            const container = document.querySelector('.container');
            const containerRect = container.getBoundingClientRect();
            const percentage = ((e.clientX - containerRect.left) / containerRect.width) * 100;
            
            // Constrain between 20% and 80%
            if (percentage > 20 && percentage < 80) {
                // Use flex-basis to maintain proper flex behavior
                chatPanel.style.flex = `0 0 ${percentage}%`;
                vizPanel.style.flex = `0 0 ${100 - percentage}%`;
                
                // The new visualizer handles resize automatically through D3
            }
        };

        const handleMouseUp = () => {
            isResizing = false;
            const container = document.querySelector('.container');
            container.classList.remove('resizing');
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            
            // After resizing is complete, the visualization will auto-adjust
            console.log('Resize complete - visualization auto-adjusting');
        };

        // Also handle touch events for mobile/tablet support
        resizer.addEventListener('touchstart', (e) => {
            isResizing = true;
            document.addEventListener('touchmove', handleTouchMove);
            document.addEventListener('touchend', handleTouchEnd);
            e.preventDefault();
        });

        const handleTouchMove = (e) => {
            if (!isResizing) return;
            
            const container = document.querySelector('.container');
            const containerRect = container.getBoundingClientRect();
            const touch = e.touches[0];
            const percentage = ((touch.clientX - containerRect.left) / containerRect.width) * 100;
            
            // Constrain between 20% and 80%
            if (percentage > 20 && percentage < 80) {
                chatPanel.style.flex = `0 0 ${percentage}%`;
                vizPanel.style.flex = `0 0 ${100 - percentage}%`;
                
                // Trigger resize for visualization during dragging
                if (this.visualizer) {
                    this.visualizer.resize();
                }
            }
        };

        const handleTouchEnd = () => {
            isResizing = false;
            document.removeEventListener('touchmove', handleTouchMove);
            document.removeEventListener('touchend', handleTouchEnd);
            
            // After resizing is complete, the visualization will auto-adjust
            console.log('Touch resize complete - visualization auto-adjusting');
        };
    }

    initializeVisualization() {
        // Initialize the research tree visualizer
        const vizContent = document.getElementById('vizContent');
        const config = new VisualizationConfigD3({
            node_radius: 25,
            node_font_size: 12,
            animation_duration: 750,
            width: vizContent.offsetWidth || 1200,
            height: vizContent.offsetHeight || 800
        });
        
        this.visualizer = new ResearchVisualizer("research_progress.json", config);
        
        console.log('Research visualization initialized');
    }

    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message || this.isResearching) return;

        // Add user message to chat
        this.addMessage('user', message);
        this.messageInput.value = '';
        this.sendBtn.disabled = true;
        this.isResearching = true;

        // Show research running state immediately
        this.showResearchRunningState();

        try {
            // Start research
            const response = await fetch('/api/start_research', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: message })
            });

            const data = await response.json();
            
            if (response.ok) {
                this.currentSessionId = data.session_id;
                this.socket.emit('join_session', { session_id: this.currentSessionId });
                this.showProgress(true);
                this.addStatusMessage('info', 'Research started! Building research tree...');
            } else {
                throw new Error(data.error || 'Failed to start research');
            }
        } catch (error) {
            console.error('Error starting research:', error);
            this.addStatusMessage('error', `Error: ${error.message}`);
            this.resetState();
        }
    }

    formatContentBasic(content) {
        // Basic markdown-like formatting without a library
        return content
            // Headers
            .replace(/^### (.*$)/gm, '<h3>$1</h3>')
            .replace(/^## (.*$)/gm, '<h2>$1</h2>')
            .replace(/^# (.*$)/gm, '<h1>$1</h1>')
            // Bold and italic
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Lists
            .replace(/^- (.*$)/gm, '<li>$1</li>')
            .replace(/^(\d+)\. (.*$)/gm, '<li>$1. $2</li>')
            // Line breaks
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n/g, '<br>')
            // Wrap in paragraphs
            .replace(/^(.*)$/, '<p>$1</p>')
            // Clean up list items
            .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
            .replace(/<\/ul>\s*<ul>/g, '');
    }

    getOperationDisplayName(operation) {
        const operationNames = {
            'plan': 'Planning Phase',
            'research': 'Research Phase', 
            'agent_selection': 'Agent Selection',
            'search_planning': 'Search Planning',
            'subquery_execution': 'Subquery Execution',
            'research_execution': 'Research Execution',
            'report_writing': 'Report Writing',
            'default': 'Research Phase'
        };
        return operationNames[operation] || operationNames['default'];
    }

    analyzeNodesProgress(nodes) {
        if (!nodes || nodes.length === 0) {
            return { message: 'No research nodes yet', details: '' };
        }

        // Count nodes by operation type
        const operationCounts = {};
        const statusCounts = { started: 0, running: 0, completed: 0, error: 0 };
        
        nodes.forEach(node => {
            const operation = node.operation || 'default';
            operationCounts[operation] = (operationCounts[operation] || 0) + 1;
            
            const status = node.status || 'started';
            statusCounts[status] = (statusCounts[status] || 0) + 1;
        });

        // Find the most recent operation type
        const operations = Object.keys(operationCounts);
        let currentOperation = 'default';
        let currentOperationCount = 0;
        
        // Prioritize current activity (started/running nodes)
        for (const node of nodes) {
            if (node.status === 'started' || node.status === 'running') {
                currentOperation = node.operation || 'default';
                break;
            }
        }
        
        // If no active nodes, use the most common operation
        if (currentOperation === 'default' && operations.length > 0) {
            currentOperation = operations.reduce((a, b) => 
                operationCounts[a] > operationCounts[b] ? a : b
            );
        }
        
        currentOperationCount = operationCounts[currentOperation] || 0;
        
        const operationName = this.getOperationDisplayName(currentOperation);
        const totalNodes = nodes.length;
        const completedNodes = statusCounts.completed || 0;
        const activeNodes = statusCounts.started + statusCounts.running;
        
        let message = `🚀 Research Progress`;
        let details = '';
        
        if (activeNodes > 0) {
            message += `: ${completedNodes}/${totalNodes} completed, ${activeNodes} ongoing`;
            details = `${completedNodes}/${totalNodes} completed, ${activeNodes} ongoing`;
        } else if (completedNodes === totalNodes) {
            message = `📊 Research completed! Writing report...`;
            details = `Research tree fully built`;
        } else {
            message += `: ${completedNodes}/${totalNodes} completed`;
            details = `${completedNodes}/${totalNodes} completed`;
        }
        
        return { message, details };
    }

    addMessage(type, content, time = null, isReport = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        if (type === 'assistant') {
            // Check if content is wrapped in markdown code blocks
            let processedContent = content;
            const markdownCodeBlockRegex = /```markdown\s([\s\S]*?)```/;
            const codeBlockMatch = content.match(markdownCodeBlockRegex);
            
            if (codeBlockMatch) {
                // Extract content from markdown code block
                processedContent = codeBlockMatch[1];
                console.log('Extracted content from markdown code block');
            }
            
            // Check if content looks like markdown (multiple indicators)
            const isMarkdown = processedContent.includes('# ') || 
                              processedContent.includes('## ') || 
                              processedContent.includes('**') || 
                              processedContent.includes('*') ||
                              processedContent.includes('\n- ') ||
                              processedContent.includes('\n1. ') ||
                              processedContent.includes('```') ||
                              processedContent.length > 500 || // Long content is likely a report
                              codeBlockMatch; // Content was in markdown code block
            
            console.log('Content markdown detection:', {
                hasHeader: processedContent.includes('# '),
                hasHeader2: processedContent.includes('## '),
                hasBold: processedContent.includes('**'),
                hasItalic: processedContent.includes('*'),
                hasList: processedContent.includes('\n- '),
                hasOrderedList: processedContent.includes('\n1. '),
                hasCode: processedContent.includes('```'),
                isLong: processedContent.length > 500,
                inCodeBlock: !!codeBlockMatch,
                isMarkdown: isMarkdown,
                contentLength: processedContent.length
            });
            
            if (isMarkdown) {
                try {
                    // Check if marked is available
                    if (typeof marked !== 'undefined') {
                        // Render markdown for reports
                        contentDiv.innerHTML = marked.parse(processedContent);
                        contentDiv.classList.add('report-content');
                        console.log('Successfully rendered markdown content');
                    } else {
                        console.warn('Marked library not available, using fallback formatting');
                        // Fallback to basic formatting
                        contentDiv.innerHTML = this.formatContentBasic(processedContent);
                        contentDiv.classList.add('report-content');
                    }
                } catch (error) {
                    console.error('Error parsing markdown:', error);
                    // Fallback to basic formatting
                    contentDiv.innerHTML = this.formatContentBasic(processedContent);
                    contentDiv.classList.add('report-content');
                }
            } else {
                contentDiv.textContent = processedContent;
            }
        } else {
            contentDiv.textContent = content;
        }
        
        // Create time and download section
        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.style.cssText = isReport && type === 'assistant' ? 
            'display: flex; justify-content: space-between; align-items: center; margin-top: 8px;' : 
            '';
        
        const timeSpan = document.createElement('span');
        timeSpan.textContent = time || new Date().toLocaleTimeString();
        timeDiv.appendChild(timeSpan);
        
        // Add download button for reports inline with timestamp
        if (isReport && type === 'assistant') {
            const downloadBtn = document.createElement('button');
            downloadBtn.className = 'download-btn';
            downloadBtn.innerHTML = '📄 Download';
            downloadBtn.style.cssText = `
                background: #007bff;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                cursor: pointer;
                font-size: 11px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
                transition: background-color 0.2s;
                margin-left: auto;
            `;
            
            downloadBtn.addEventListener('mouseover', () => {
                downloadBtn.style.background = '#0056b3';
            });
            
            downloadBtn.addEventListener('mouseout', () => {
                downloadBtn.style.background = '#007bff';
            });
            
            downloadBtn.addEventListener('click', () => {
                this.downloadReport();
            });
            
            timeDiv.appendChild(downloadBtn);
        }
        
        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timeDiv);
        
        // Store current scroll position before adding content
        const chatContainer = this.chatMessages;
        const wasScrolledToBottom = chatContainer.scrollHeight - chatContainer.clientHeight <= chatContainer.scrollTop + 1;
        
        this.chatMessages.appendChild(messageDiv);
        
        // Only auto-scroll if user was already at bottom or if it's not a report
        if (!isReport || wasScrolledToBottom) {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        } else {
            // For reports, scroll to show the beginning of the report
            setTimeout(() => {
                // Calculate the position to show the top of the report message
                const containerTop = chatContainer.scrollTop;
                const messageTop = messageDiv.offsetTop;
                const containerHeight = chatContainer.clientHeight;
                
                // Scroll to show the start of the message with some padding from the top
                const targetScrollTop = messageTop - 20; // 20px padding from top
                
                // Ensure we don't scroll past the beginning or beyond what's necessary
                const finalScrollTop = Math.max(0, Math.min(targetScrollTop, chatContainer.scrollHeight - containerHeight));
                chatContainer.scrollTop = finalScrollTop;
                
                console.log('Report positioned at top for reading');
            }, 150); // Slightly longer delay to ensure proper rendering
        }
    }

    addStatusMessage(type, message, updateLast = false, noScroll = false) {
        if (updateLast && this.lastStatusMessageElement) {
            // Update the existing status message
            this.lastStatusMessageElement.textContent = message;
            this.lastStatusMessageElement.className = `status-message ${type}`;
            return;
        }

        const statusDiv = document.createElement('div');
        statusDiv.className = `status-message ${type}`;
        statusDiv.textContent = message;
        
        this.chatMessages.appendChild(statusDiv);
        
        // Only auto-scroll if not suppressed
        if (!noScroll) {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }
        
        // Track this as the last status message if it's a progress update
        if (type === 'info' && (message.includes('Research') || message.includes('nodes'))) {
            this.lastStatusMessageElement = statusDiv;
        }
    }

    updateStatus(message) {
        // Progress text element removed, just log the status
        console.log('Status update:', message);
    }

    updateProgress(progress) {
        // Progress elements removed, just log the progress
        console.log('Progress update:', progress);
    }

    async updateVisualization(nodes, edges = []) {
        console.log('Updating visualization with nodes:', nodes);
        console.log('Nodes count:', nodes ? nodes.length : 0);
        console.log('Edge count:', edges ? edges.length : 0);
        console.log('Node structure sample:', nodes && nodes.length > 0 ? nodes[0] : 'none');
        console.log('Using visualizer:', this.visualizer ? this.visualizer.constructor.name : 'none');
        
        if (!this.visualizer) {
            console.warn('Visualizer not initialized');
            return;
        }

        // Validate nodes parameter
        if (!Array.isArray(nodes)) {
            console.error('updateVisualization received non-array nodes:', nodes);
            this.addStatusMessage('error', 'Invalid visualization data: nodes must be an array');
            return;
        }

        if (nodes.length === 0) {
            console.log('No nodes to display');
            this.clearVisualization();
            return;
        }

        // Validate edges parameter
        if (!Array.isArray(edges)) {
            console.warn('updateVisualization received non-array edges, defaulting to empty array:', edges);
            edges = [];
        }

        // Hide all placeholder states when showing actual visualization
        this.hideAllPlaceholderStates();

        // Debounce visualization updates to prevent frequent shaking
        if (this.visualizationUpdateTimeout) {
            clearTimeout(this.visualizationUpdateTimeout);
        }
        
        this.visualizationUpdateTimeout = setTimeout(async () => {
            try {
                // Create log data structure expected by the visualizer
                const logData = {
                    nodes: nodes,
                    edges: edges.map(edge => ({
                        from: edge.source || edge.from,
                        to: edge.target || edge.to
                    }))
                };

                // Render visualization to the container
                await this.visualizer.renderToContainer('#vizContent', logData);
                
                // Analyze progress and create descriptive status message
                const progressInfo = this.analyzeNodesProgress(nodes);
                console.log('Progress analysis:', progressInfo);
                
                // Update or add status message about visualization update
                this.addStatusMessage('info', progressInfo.message, true);
            } catch (error) {
                console.error('Error updating visualization:', error);
                this.addStatusMessage('error', 'Failed to update visualization');
            }
        }, 100); // 100ms debounce delay
    }

    checkForTerminatedNodes(nodes) {
        if (!Array.isArray(nodes)) return;
        
        // Check for newly terminated nodes
        nodes.forEach(node => {
            const nodeId = node.id;
            const currentStatus = node.status;
            const previousNode = this.previousNodes.get(nodeId);
            
            // If node was not terminated before but is now terminated
            if (previousNode && previousNode.status !== 'terminated' && currentStatus === 'terminated') {
                this.showTerminationNotification(nodeId);
            }
            
            // Update previous node state
            this.previousNodes.set(nodeId, { status: currentStatus });
        });
    }

    showTerminationNotification(nodeId) {
        const notification = document.createElement('div');
        notification.className = 'termination-notification';
        notification.innerHTML = `
            <div class="notification-content">
                <strong>Node ${nodeId} Terminated</strong>
                <p>Terminated by the Runtime Orchestrator after achieving its research goal.</p>
            </div>
            <button class="notification-close">&times;</button>
        `;
        
        // Add to body
        document.body.appendChild(notification);
        
        // Add to notification stack
        this.notificationStack.push(notification);
        
        // Position notification based on stack
        this.updateNotificationPositions();
        
        // Animate in
        setTimeout(() => {
            notification.classList.add('show');
        }, 10);
        
        // Auto remove after 5 seconds
        const autoRemoveTimeout = setTimeout(() => {
            this.removeNotification(notification);
        }, 5000);
        
        // Store timeout reference for cleanup
        notification._autoRemoveTimeout = autoRemoveTimeout;
        
        // Manual close handler
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => {
            clearTimeout(autoRemoveTimeout);
            this.removeNotification(notification);
        });
    }

    updateNotificationPositions() {
        const topMargin = 20;
        const notificationHeight = 80; // Approximate height including margins
        
        this.notificationStack.forEach((notification, index) => {
            if (notification.parentNode) {
                const topPosition = topMargin + (index * notificationHeight);
                notification.style.top = `${topPosition}px`;
            }
        });
    }

    removeNotification(notification) {
        if (notification && notification.parentNode) {
            // Clear auto-remove timeout if it exists
            if (notification._autoRemoveTimeout) {
                clearTimeout(notification._autoRemoveTimeout);
            }
            
            // Remove from stack
            const index = this.notificationStack.indexOf(notification);
            if (index > -1) {
                this.notificationStack.splice(index, 1);
            }
            
            // Animate out
            notification.classList.remove('show');
            notification.classList.add('hide');
            
            // Update positions of remaining notifications
            this.updateNotificationPositions();
            
            // Remove from DOM after animation
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }
    }

    hideAllPlaceholderStates() {
        const emptyViz = document.getElementById('emptyViz');
        const loadingViz = document.getElementById('loadingViz');
        const researchRunningViz = document.getElementById('researchRunningViz');
        
        if (emptyViz) emptyViz.style.display = 'none';
        if (loadingViz) loadingViz.style.display = 'none';
        if (researchRunningViz) researchRunningViz.style.display = 'none';
    }

    showResearchRunningState() {
        this.hideAllPlaceholderStates();
        const researchRunningViz = document.getElementById('researchRunningViz');
        if (researchRunningViz) {
            researchRunningViz.style.display = 'flex';
        }
        
        // Clear any existing visualization
        this.clearVisualization();
    }

    clearVisualization() {
        const vizContent = document.getElementById('vizContent');
        if (vizContent) {
            // Clear all SVG content
            const svgs = vizContent.querySelectorAll('svg');
            svgs.forEach(svg => svg.remove());
            
            // Clear all D3 tooltip elements
            const tooltips = document.querySelectorAll('.tooltip, .research-tooltip');
            tooltips.forEach(tooltip => tooltip.remove());
        }
        
        // Show empty state only if not in research running state
        const researchRunningViz = document.getElementById('researchRunningViz');
        if (!researchRunningViz || researchRunningViz.style.display === 'none') {
            this.showEmptyState();
        }
    }

    showNodeInfo(nodeData) {
        console.log('Showing info for node:', nodeData);
        
        // Use the visualizer's node info generation if available
        let infoHtml;
        if (this.visualizer && this.visualizer._createNodeInfoHTML) {
            infoHtml = this.visualizer._createNodeInfoHTML(nodeData);
        } else {
            // Fallback to basic info display
            infoHtml = `<h3>Node ${nodeData.id} Details</h3>`;
            infoHtml += `<div style="margin-bottom: 15px;">`;
            infoHtml += `<strong>Status:</strong> <span style="color: ${this.getStatusColor(nodeData.status)}">${(nodeData.status || 'Unknown').toUpperCase()}</span><br/>`;
            infoHtml += `<strong>Depth:</strong> ${nodeData.depth || 'N/A'}<br/>`;
            
            if (nodeData.operation) {
                infoHtml += `<strong>Operation:</strong> ${nodeData.operation.replace('_', ' ')}<br/>`;
            }
            
            if (nodeData.start_time) {
                infoHtml += `<strong>Start Time:</strong> ${new Date(nodeData.start_time).toLocaleString()}<br/>`;
            }
            
            if (nodeData.duration) {
                infoHtml += `<strong>Duration:</strong> ${nodeData.duration}<br/>`;
            }
            
            if (nodeData.query) {
                infoHtml += `<strong>Query:</strong><br/><div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0; max-height: 150px; overflow-y: auto;">${nodeData.query}</div>`;
            }
            
            if (nodeData.results) {
                const resultsText = typeof nodeData.results === 'string' ? nodeData.results : JSON.stringify(nodeData.results, null, 2);
                infoHtml += `<strong>Results:</strong><br/><div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0; max-height: 200px; overflow-y: auto;"><pre>${resultsText}</pre></div>`;
            }
            
            infoHtml += `</div>`;
        }
        
        this.infoPanelContent.innerHTML = infoHtml;
        this.infoPanel.style.display = 'block';
    }

    getStatusColor(status) {
        const colors = {
            'started': '#1976d2',
            'running': '#ff9800',
            'completed': '#2e7d32',
            'error': '#c62828',
            'terminated': '#FF8706',
            'cancelled': '#FFBF00'
        };
        return colors[status] || '#666';
    }

    closeInfoPanel() {
        this.infoPanel.style.display = 'none';
    }

    downloadReport() {
        if (!this.lastReportContent) {
            console.warn('No report content available for download');
            alert('No report available for download. Please complete a research session first.');
            return;
        }

        try {
            // Create a blob with the markdown content
            const blob = new Blob([this.lastReportContent], { type: 'text/markdown;charset=utf-8' });
            
            // Create a download link
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            
            // Generate filename with timestamp
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            link.download = `research-report-${timestamp}.md`;
            
            // Add some attributes for better compatibility
            link.style.display = 'none';
            
            // Trigger download
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            // Clean up the URL object
            setTimeout(() => URL.revokeObjectURL(url), 100);
            
            console.log('Report downloaded successfully');
            
            // Show brief success feedback on the most recent download button
            const downloadBtns = document.querySelectorAll('.download-btn');
            const downloadBtn = downloadBtns[downloadBtns.length - 1]; // Get the most recent one
            if (downloadBtn) {
                const originalText = downloadBtn.innerHTML;
                downloadBtn.innerHTML = '✅ Downloaded';
                downloadBtn.style.background = '#28a745';
                setTimeout(() => {
                    downloadBtn.innerHTML = originalText;
                    downloadBtn.style.background = '#007bff';
                }, 2000);
            }
        } catch (error) {
            console.error('Error downloading report:', error);
            alert('Failed to download report. Please try again.');
        }
    }

    showProgress(show) {
        // Show/hide loading state in visualization area
        if (show) {
            this.showLoadingState();
        } else {
            this.hideLoadingState();
        }
        console.log('Progress visibility:', show ? 'show' : 'hide');
    }

    showLoadingState() {
        const emptyViz = document.getElementById('emptyViz');
        const loadingViz = document.getElementById('loadingViz');
        
        if (emptyViz) emptyViz.style.display = 'none';
        if (loadingViz) loadingViz.style.display = 'flex';
        
        // Clear any existing visualization
        this.clearVisualization();
        
        // Start the loading text rotation
        this.startLoadingTextRotation();
    }

    startLoadingTextRotation() {
        const loadingTexts = [
            'Research in Progress',
            'Analyzing your query',
            'Building research tree',
            'Gathering insights',
            'Processing information'
        ];
        
        const loadingDescriptions = [
            'Analyzing your query and building the research tree...',
            'Breaking down the research into sub-topics...',
            'Gathering relevant information from sources...',
            'Connecting related concepts and ideas...',
            'Organizing the research structure...'
        ];
        
        let currentIndex = 0;
        const loadingTextElement = document.querySelector('.loading-text');
        const loadingDescElement = document.querySelector('.loading-description');
        
        if (loadingTextElement && loadingDescElement) {
            // Update text every 2 seconds
            this.loadingInterval = setInterval(() => {
                currentIndex = (currentIndex + 1) % loadingTexts.length;
                loadingTextElement.textContent = loadingTexts[currentIndex];
                loadingDescElement.textContent = loadingDescriptions[currentIndex];
            }, 2000);
        }
    }

    hideLoadingState() {
        const emptyViz = document.getElementById('emptyViz');
        const loadingViz = document.getElementById('loadingViz');
        
        if (loadingViz) loadingViz.style.display = 'none';
        
        // Stop loading text rotation
        if (this.loadingInterval) {
            clearInterval(this.loadingInterval);
            this.loadingInterval = null;
        }
        
        // Check if there's an active visualization, if not, show empty state
        if (!this.visualizer || !this.currentSessionId) {
            if (emptyViz) emptyViz.style.display = 'flex';
        }
    }

    showEmptyState() {
        const emptyViz = document.getElementById('emptyViz');
        const loadingViz = document.getElementById('loadingViz');
        const researchRunningViz = document.getElementById('researchRunningViz');
        
        if (loadingViz) loadingViz.style.display = 'none';
        if (researchRunningViz) researchRunningViz.style.display = 'none';
        if (emptyViz) emptyViz.style.display = 'flex';
    }

    onResearchComplete(data) {
        console.log('Research completed:', data);
        console.log('Report content preview:', data.report.substring(0, 200) + '...');
        console.log('Report contains markdown headers:', data.report.includes('#'));
        console.log('Report contains markdown bold:', data.report.includes('**'));
        
        console.log('Displaying report without auto-scroll to bottom');
        
        // Store the raw markdown content for downloading
        let reportContent = data.report;
        
        // Extract content from markdown code blocks if wrapped
        const markdownCodeBlockRegex = /```markdown\s([\s\S]*?)```/;
        const codeBlockMatch = reportContent.match(markdownCodeBlockRegex);
        if (codeBlockMatch) {
            reportContent = codeBlockMatch[1];
        }
        
        this.lastReportContent = reportContent;
        
        // Add the report as a special message that doesn't auto-scroll
        this.addMessage('assistant', data.report, null, true);
        this.addStatusMessage('success', 'Research completed successfully!', false, true); // Don't scroll
        this.resetState();
    }

    onResearchError(data) {
        console.error('Research error:', data);
        this.addStatusMessage('error', `Research failed: ${data.error}`);
        this.resetState();
    }

    resetState() {
        this.isResearching = false;
        this.sendBtn.disabled = false;
        this.showProgress(false);
        this.currentSessionId = null;
        this.lastStatusMessageElement = null; // Clear tracking of last status message
        // Note: Keep lastReportContent available for download even after reset
        
        // Show empty state when no research is active
        this.showEmptyState();
    }
}

// Initialize the application when the page loads
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing Deep Research App...');
    window.researchApp = new DeepResearchApp();
    console.log('App initialized successfully');
});
