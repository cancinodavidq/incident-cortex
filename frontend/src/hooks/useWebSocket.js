import { useState, useEffect, useRef, useCallback } from 'react';

export function useWebSocket(incidentId) {
  const [messages, setMessages] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const RECONNECT_INTERVAL = 3000; // 3 seconds

  const connect = useCallback(() => {
    if (!incidentId || wsRef.current) return;

    try {
      // Connect directly to backend — CRA dev proxy doesn't forward WS upgrades
      const apiUrl = process.env.REACT_APP_API_URL || 'http://localhost:8000';
      const wsUrl = apiUrl.replace(/^http/, 'ws') + `/ws/${incidentId}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log(`WebSocket connected for incident ${incidentId}`);
        setConnected(true);
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setMessages((prev) => [...prev, data]);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setConnected(false);
        wsRef.current = null;

        // Attempt to reconnect with exponential backoff
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1;
          const delayMs = RECONNECT_INTERVAL * Math.pow(1.5, reconnectAttemptsRef.current - 1);

          console.log(`Reconnecting in ${delayMs}ms (attempt ${reconnectAttemptsRef.current})`);
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delayMs);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setConnected(false);
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setConnected(false);
    }
  }, [incidentId]);

  useEffect(() => {
    connect();

    // Cleanup on unmount
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [incidentId, connect]);

  return { messages, connected };
}
