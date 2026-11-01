import React from 'react';
import {AbsoluteFill} from 'remotion';

export interface SafeZoneOverlayProps {
  visible?: boolean;
}

export const SafeZoneOverlay: React.FC<SafeZoneOverlayProps> = ({visible = false}) => {
  if (!visible) return null;
  return (
    <AbsoluteFill style={{pointerEvents: 'none', zIndex: 9999}}>
      {/* Top UI blocked area (220px) */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 220,
          backgroundColor: 'rgba(239, 68, 68, 0.25)',
          borderBottom: '2px dashed #ef4444',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            color: '#ffffff',
            fontSize: 22,
            fontWeight: 700,
            padding: '4px 12px',
            borderRadius: 6,
            backgroundColor: '#ef4444',
          }}
        >
          Top UI Safe Line (220px)
        </span>
      </div>

      {/* Bottom UI blocked area (460px) */}
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: 460,
          backgroundColor: 'rgba(239, 68, 68, 0.25)',
          borderTop: '2px dashed #ef4444',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            color: '#ffffff',
            fontSize: 22,
            fontWeight: 700,
            padding: '4px 12px',
            borderRadius: 6,
            backgroundColor: '#ef4444',
          }}
        >
          Bottom Description & Audio Safe Line (460px)
        </span>
      </div>

      {/* Right action buttons blocked area (140px) */}
      <div
        style={{
          position: 'absolute',
          top: 220,
          bottom: 460,
          right: 0,
          width: 140,
          backgroundColor: 'rgba(245, 158, 11, 0.25)',
          borderLeft: '2px dashed #f59e0b',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            color: '#ffffff',
            fontSize: 18,
            fontWeight: 700,
            padding: '6px 4px',
            writingMode: 'vertical-rl',
            borderRadius: 6,
            backgroundColor: '#f59e0b',
          }}
        >
          Action Icons (140px)
        </span>
      </div>

      {/* Safe viewport bounds */}
      <div
        style={{
          position: 'absolute',
          top: 220,
          bottom: 460,
          left: 60,
          right: 140,
          border: '2px solid rgba(16, 185, 129, 0.8)',
          boxShadow: 'inset 0 0 20px rgba(16, 185, 129, 0.2)',
          pointerEvents: 'none',
        }}
      />
    </AbsoluteFill>
  );
};
