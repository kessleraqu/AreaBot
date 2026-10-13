(() => {
    const tabs = Array.from(document.querySelectorAll('.tab-button'));
    const panels = Array.from(document.querySelectorAll('.tab-panel'));
    const chatLog = document.getElementById('chat-log');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const sendButton = chatForm?.querySelector('.send-button') || null;
    const thinkingIndicator = document.getElementById('thinking-indicator');
    const indicatorHome = thinkingIndicator?.parentElement || null;
    const pdfInput = document.getElementById('pdf-input');
    const uploadBtn = document.getElementById('upload-btn');
    const processBtn = document.getElementById('process-btn');
    const pendingList = document.getElementById('pending-list');
    const processedList = document.getElementById('processed-list');
    const pdfFeedback = document.getElementById('pdf-feedback');

    let sessionId = null;
    const conversation = [];
    const introMessage = [
        '**¡Hola! Soy Area Bot.**',
        'Tu asistente de soporte técnico para Area Cooling Solutions.',
        '',
        'Puedes pedirme ayuda con:',
        '- Guía para dimensionar y seleccionar productos',
        '- Resolución de problemas y diagnósticos',
        '- Recomendaciones de aplicación o configuración',
        '',
        '¿Cómo puedo ayudarte hoy?'
    ].join('\n');

    function appendInlineContent(target, text) {
        if (!text) {
            return;
        }
        const boldRegex = /(\*\*|__)(.+?)\1/g;
        let lastIndex = 0;
        let match;
        while ((match = boldRegex.exec(text)) !== null) {
            if (match.index > lastIndex) {
                target.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
            }
            const strong = document.createElement('strong');
            strong.textContent = match[2];
            target.appendChild(strong);
            lastIndex = boldRegex.lastIndex;
        }
        if (lastIndex < text.length) {
            target.appendChild(document.createTextNode(text.slice(lastIndex)));
        }
    }

    function scrollChatToBottom(options = {}) {
        if (!chatLog) {
            return;
        }
        const { smooth = false } = options;
        const behavior = smooth ? 'smooth' : 'auto';
        requestAnimationFrame(() => {
            chatLog.scrollTo({ top: chatLog.scrollHeight, behavior });
            if (!chatForm) {
                return;
            }
            const formRect = chatForm.getBoundingClientRect();
            if (formRect.bottom > window.innerHeight) {
                chatForm.scrollIntoView({ block: 'end', behavior });
            }
        });
    }

    function renderAssistantContent(container, text) {
        if (!container) {
            return;
        }
        const messageText = typeof text === 'string' ? text : '';
        container.replaceChildren();
        const lines = messageText.split(/\r?\n/);
        let listElement = null;
        lines.forEach((rawLine) => {
            const trimmed = rawLine.trim();
            if (!trimmed) {
                listElement = null;
                return;
            }
            const bulletMatch = trimmed.match(/^[-*]\s+(.*)$/);
            if (bulletMatch) {
                if (!listElement) {
                    listElement = document.createElement('ul');
                    container.appendChild(listElement);
                }
                const li = document.createElement('li');
                appendInlineContent(li, bulletMatch[1]);
                listElement.appendChild(li);
                return;
            }
            listElement = null;
            const paragraph = document.createElement('p');
            appendInlineContent(paragraph, rawLine);
            container.appendChild(paragraph);
        });
        if (!container.childNodes.length && messageText) {
            const paragraph = document.createElement('p');
            appendInlineContent(paragraph, messageText);
            container.appendChild(paragraph);
        }
        const hasContent = container.childNodes.length > 0 && messageText.trim().length > 0;
        container.classList.toggle('placeholder', !hasContent);
        // Show/hide the bubble based on content
        if (hasContent) {
            container.style.visibility = 'visible';
            container.style.opacity = '1';
        } else {
            container.style.visibility = 'hidden';
            container.style.opacity = '0';
        }
    }

    function updateSendButtonState() {
        if (!sendButton || !chatInput) {
            return;
        }
        const hasValue = chatInput.value.trim().length > 0;
        sendButton.disabled = !hasValue;
        sendButton.setAttribute('aria-disabled', (!hasValue).toString());
    }

    function autoResizeInput() {
        if (!chatInput) {
            return;
        }
        chatInput.style.height = 'auto';
        const maxHeight = 200;
        const minHeight = 52;
        const contentHeight = chatInput.scrollHeight;
        const next = Math.min(contentHeight, maxHeight);
        chatInput.style.height = `${Math.max(next, minHeight)}px`;
        chatInput.style.overflowY = contentHeight > maxHeight ? 'auto' : 'hidden';
        if (chatForm) {
            chatForm.style.setProperty('--chat-input-height', `${chatInput.offsetHeight}px`);
        }
        updateSendButtonState();
    }

    autoResizeInput();
    chatInput?.addEventListener('input', autoResizeInput);
    chatInput?.addEventListener('focus', autoResizeInput);
    // Allow Enter to submit the message and Shift+Enter to insert a newline
    function sendCurrentMessage() {
        const text = chatInput.value.trim();
        if (!text) {
            return false;
        }
        chatInput.value = '';
        autoResizeInput();
        sendMessage(text);
        return true;
    }

    chatInput?.addEventListener('keydown', (evt) => {
        if (evt.key === 'Enter' && !evt.shiftKey) {
            // Prevent inserting a newline and submit instead
            evt.preventDefault();
            sendCurrentMessage();
        }
    });

    function setIndicatorPhase(phase) {
        if (!thinkingIndicator) {
            return;
        }
        thinkingIndicator.classList.remove('thinking', 'resting');
        if (phase === 'thinking') {
            thinkingIndicator.classList.add('thinking');
        } else {
            thinkingIndicator.classList.add('resting');
        }
    }

    function showIndicator() {
        if (!thinkingIndicator) {
            return;
        }
        thinkingIndicator.classList.remove('hidden');
    }

    function hideIndicator() {
        if (!thinkingIndicator) {
            return;
        }
        thinkingIndicator.classList.add('hidden');
    }

    function dockIndicator(slot) {
        if (!thinkingIndicator || !slot) {
            return;
        }
        slot.appendChild(thinkingIndicator);
        showIndicator();
        thinkingIndicator.classList.remove('home');
        thinkingIndicator.classList.add('docked');
    }
    function sendIndicatorHome(options = {}) {
        if (!thinkingIndicator || !indicatorHome) {
            return;
        }
        indicatorHome.insertBefore(thinkingIndicator, indicatorHome.firstChild || null);
        thinkingIndicator.classList.remove('docked');
        thinkingIndicator.classList.add('home');
        if (options.hide || !chatLog.querySelector('.message.assistant')) {
            hideIndicator();
        }
    }

    function updateIndicatorPlacement(preferredSlot) {
        if (!thinkingIndicator) {
            return;
        }
        if (preferredSlot) {
            dockIndicator(preferredSlot);
            return;
        }
        const assistantMessages = chatLog.querySelectorAll('.message.assistant');
        const lastAssistant = assistantMessages[assistantMessages.length - 1];
        const slot = lastAssistant?.querySelector('.indicator-slot');
        if (slot) {
            dockIndicator(slot);
        } else {
            sendIndicatorHome({ hide: true });
        }
    }

    function switchTab(targetId) {
        tabs.forEach((tab) => {
            const active = tab.dataset.target === targetId;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active.toString());
        });
        panels.forEach((panel) => {
            const active = panel.id === targetId;
            panel.classList.toggle('active', active);
            panel.setAttribute('aria-hidden', (!active).toString());
        });
    }

    tabs.forEach((tab) => {
        tab.addEventListener('click', () => switchTab(tab.dataset.target));
    });

    function appendMessage(role, content = '') {
        const message = document.createElement('div');
        message.className = `message ${role}`;

        if (role === 'assistant') {
            const slot = document.createElement('div');
            slot.className = 'indicator-slot';

            const contentWrapper = document.createElement('div');
            contentWrapper.className = 'message-content';
            
            // Only create bubble if there's content
            let bubble = null;
            if (content) {
                bubble = document.createElement('div');
                bubble.className = 'bubble';
                renderAssistantContent(bubble, content);
                contentWrapper.appendChild(bubble);
            }

            message.appendChild(slot);
            message.appendChild(contentWrapper);
            chatLog.appendChild(message);
            scrollChatToBottom();
            return { message, bubble, slot, contentWrapper };
        }

        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.textContent = content;
        message.appendChild(bubble);
        chatLog.appendChild(message);
        scrollChatToBottom();
        return { message, bubble };
    }

    async function sendMessage(text) {
        appendMessage('user', text);
        conversation.push({ user: text });

        const assistantEntry = appendMessage('assistant');
        updateIndicatorPlacement(assistantEntry.slot);
        setIndicatorPhase('thinking');
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulated = '';
        let streamFinished = false;
        let indicatorDismissed = false;

        try {
            const response = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: text,
                    session_id: sessionId
                })
            });

            if (!response.ok || !response.body) {
                const detail = await response.json().catch(() => ({}));
                throw new Error(detail.detail || 'La solicitud de chat falló');
            }

            const reader = response.body.getReader();
            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.trim()) {
                        continue;
                    }
                    let event;
                    try {
                        event = JSON.parse(line);
                    } catch (parseError) {
                        continue;
                    }
                    if (event.type === 'session' && event.session_id) {
                        sessionId = event.session_id;
                    } else if (event.type === 'delta' && typeof event.text === 'string') {
                        if (!indicatorDismissed) {
                            indicatorDismissed = true;
                            setIndicatorPhase('resting');
                            sendIndicatorHome({ hide: true });
                        }
                        accumulated += event.text;
                        // Create bubble on first content
                        if (!assistantEntry.bubble) {
                            assistantEntry.bubble = document.createElement('div');
                            assistantEntry.bubble.className = 'bubble';
                            assistantEntry.contentWrapper.appendChild(assistantEntry.bubble);
                        }
                        renderAssistantContent(assistantEntry.bubble, accumulated);
                        scrollChatToBottom();
                    } else if (event.type === 'done') {
                        streamFinished = true;
                    } else if (event.type === 'error') {
                        throw new Error(event.error || 'Error en la transmisión');
                    }
                }
                if (streamFinished) {
                    await reader.cancel();
                    break;
                }
            }

            if (buffer.trim()) {
                try {
                    const trailingEvent = JSON.parse(buffer);
                    if (trailingEvent.type === 'delta' && typeof trailingEvent.text === 'string') {
                        accumulated += trailingEvent.text;
                    } else if (trailingEvent.type === 'error') {
                        throw new Error(trailingEvent.error || 'Error en la transmisión');
                    } else if (trailingEvent.type === 'session' && trailingEvent.session_id) {
                        sessionId = trailingEvent.session_id;
                    } else if (trailingEvent.type === 'done') {
                        streamFinished = true;
                    }
                } catch (parseError) {
                    // Ignore trailing partial chunk.
                }
            }

            if (!streamFinished && !accumulated) {
                throw new Error('La transmisión terminó de forma inesperada');
            }

            if (accumulated) {
                // Create bubble if it doesn't exist yet
                if (!assistantEntry.bubble) {
                    assistantEntry.bubble = document.createElement('div');
                    assistantEntry.bubble.className = 'bubble';
                    assistantEntry.contentWrapper.appendChild(assistantEntry.bubble);
                }
                renderAssistantContent(assistantEntry.bubble, accumulated);
                conversation[conversation.length - 1].assistant = accumulated;
            } else if (!streamFinished) {
                const fallback = 'No se recibió respuesta.';
                if (!assistantEntry.bubble) {
                    assistantEntry.bubble = document.createElement('div');
                    assistantEntry.bubble.className = 'bubble';
                    assistantEntry.contentWrapper.appendChild(assistantEntry.bubble);
                }
                renderAssistantContent(assistantEntry.bubble, fallback);
                conversation[conversation.length - 1].assistant = fallback;
            } else {
                const fallback = 'No hay respuesta disponible para esta consulta.';
                if (!assistantEntry.bubble) {
                    assistantEntry.bubble = document.createElement('div');
                    assistantEntry.bubble.className = 'bubble';
                    assistantEntry.contentWrapper.appendChild(assistantEntry.bubble);
                }
                renderAssistantContent(assistantEntry.bubble, fallback);
                conversation[conversation.length - 1].assistant = fallback;
            }
            scrollChatToBottom({ smooth: true });
        } catch (error) {
            const message = `Error: ${error.message}`;
            if (!assistantEntry.bubble) {
                assistantEntry.bubble = document.createElement('div');
                assistantEntry.bubble.className = 'bubble';
                assistantEntry.contentWrapper.appendChild(assistantEntry.bubble);
            }
            renderAssistantContent(assistantEntry.bubble, message);
            conversation[conversation.length - 1].assistant = message;
            scrollChatToBottom({ smooth: true });
        } finally {
            setIndicatorPhase('resting');
            sendIndicatorHome({ hide: true });
        }
    }

    chatForm.addEventListener('submit', (event) => {
        event.preventDefault();
        sendCurrentMessage();
    });

    function renderPdfList(container, items, extracted) {
        container.innerHTML = '';
        if (!items.length) {
            const empty = document.createElement('li');
            empty.className = 'pdf-empty';
            empty.textContent = extracted ? 'Aún no hay documentos en la base de conocimiento.' : 'No hay documentos en espera de extracción.';
            container.appendChild(empty);
            return;
        }

        items.forEach((item) => {
            const li = document.createElement('li');
            li.className = 'pdf-item';

            const title = document.createElement('div');
            title.textContent = item.name;
            li.appendChild(title);

            const meta = document.createElement('div');
            const sizeKb = Math.max(item.size / 1024, 1);
            const date = new Date(item.modified * 1000).toLocaleString();
            meta.className = 'meta';
            meta.textContent = `${sizeKb.toFixed(1)} KB • ${date}`;
            li.appendChild(meta);

            if (extracted) {
                const actions = document.createElement('div');
                actions.className = 'actions';

                const openLink = document.createElement('a');
                openLink.href = item.url;
                openLink.target = '_blank';
                openLink.rel = 'noopener';
                openLink.textContent = 'Abrir';
                actions.appendChild(openLink);

                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete';
                deleteBtn.type = 'button';
                deleteBtn.textContent = 'Eliminar';
                deleteBtn.addEventListener('click', () => handleDelete(item.name));
                actions.appendChild(deleteBtn);

                li.appendChild(actions);
            }

            container.appendChild(li);
        });
    }

    async function handleDelete(filename) {
    const confirmed = window.confirm(`¿Eliminar ${filename} de la base de conocimiento?`);
        if (!confirmed) {
            return;
        }
        try {
            const response = await fetch(`/api/pdfs/${encodeURIComponent(filename)}`, {
                method: 'DELETE'
            });
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                throw new Error(detail.detail || 'No se pudo eliminar');
            }
            await loadPdfs();
            setFeedback(`Se eliminó ${filename} de la base de conocimiento.`);
        } catch (error) {
            setFeedback(error.message, true);
        }
    }

    function setFeedback(message, isError = false) {
        pdfFeedback.textContent = message;
        pdfFeedback.style.color = isError ? '#fca5a5' : 'inherit';
    }

    async function loadPdfs() {
        try {
            const response = await fetch('/api/pdfs');
            if (!response.ok) {
                throw new Error('No se pudieron cargar los PDF');
            }
            const data = await response.json();
            renderPdfList(pendingList, data.pending || [], false);
            renderPdfList(processedList, data.processed || [], true);
        } catch (error) {
            setFeedback(error.message, true);
        }
    }

    uploadBtn.addEventListener('click', async () => {
        const files = pdfInput.files;
        if (!files || !files.length) {
            setFeedback('Selecciona uno o más archivos PDF primero.', true);
            return;
        }
        const formData = new FormData();
        Array.from(files).forEach((file) => formData.append('files', file));

        try {
            const response = await fetch('/api/pdfs/upload', {
                method: 'POST',
                body: formData
            });
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                throw new Error(detail.detail || 'La carga falló');
            }
            const data = await response.json();
            setFeedback(`Se agregaron ${data.queued.length} archivo(s) PDF a la cola de extracción.`);
            pdfInput.value = '';
            await loadPdfs();
        } catch (error) {
            setFeedback(error.message, true);
        }
    });

    processBtn.addEventListener('click', async () => {
        setFeedback('Iniciando la extracción...');
        try {
            const response = await fetch('/api/pdfs/process', { method: 'POST' });
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                throw new Error(detail.detail || 'La extracción falló');
            }
            const data = await response.json();
            const count = data.processed.length;
            setFeedback(count ? `Se extrajeron ${count} documento(s).` : 'No se procesaron documentos.');
            await loadPdfs();
        } catch (error) {
            setFeedback(error.message, true);
        }
    });

    appendMessage('assistant', introMessage);
    hideIndicator();
    sendIndicatorHome({ hide: true });
    scrollChatToBottom();

    loadPdfs();
})();
