import React, { useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import urlParse from 'url-parse';

import videojs from 'video.js';
import 'videojs-contrib-ads';
import 'videojs-ima';

import './VideoPlayerEmbed.scss';

export function formatInnerLink(url, baseUrl) {
  let link = urlParse(url, {});
  if ('' === link.origin || 'null' === link.origin || !link.origin) {
    link = urlParse(baseUrl + '/' + url.replace(/^\//g, ''), {});
  }
  return link.toString();
}

export function VideoPlayerError(props) {
  return (
    <div className="error-container">
      <div className="error-container-inner">
        <span className="icon-wrap">
          <i className="material-icons">error_outline</i>
        </span>
        <span className="msg-wrap">{props.errorMessage}</span>
      </div>
    </div>
  );
}

VideoPlayerError.propTypes = {
  errorMessage: PropTypes.string.isRequired,
};

export function VideoPlayerEmbed(props) {
  console.log("props player embed", props);
  const videoElemRef = useRef(null);
  const playerRef = useRef(null);

  const playerStates = {
    playerVolume: props.playerVolume ?? 1,
    playerSoundMuted: props.playerSoundMuted ?? false,
    videoQuality: props.videoQuality ?? 'Auto',
    videoPlaybackSpeed: props.videoPlaybackSpeed ?? 1,
    inTheaterMode: props.inTheaterMode ?? false,
  };

  const onClickNext = () => {
    props.onClickNextCallback?.();
  };

  const onClickPrevious = () => {
    props.onClickPreviousCallback?.();
  };

  const onPlayerStateUpdate = (newState) => {
    props.onStateUpdateCallback?.(newState);
  };

  const initPlayer = () => {
    if (playerRef.current || props.errorMessage || !videoElemRef.current) return;

    if (!props.inEmbed) {
      window.removeEventListener('focus', initPlayer);
      document.removeEventListener('visibilitychange', initPlayer);
      videoElemRef.current.focus();
    }

    const subtitles = {
      on: false,
      languages: [],
    };

    if (props.subtitlesInfo?.length) {
      props.subtitlesInfo.forEach((sub) => {
        if (sub.src && sub.srclang && sub.label) {
          subtitles.languages.push({
            src: formatInnerLink(sub.src, props.siteUrl),
            srclang: sub.srclang,
            label: sub.label,
          });
        }
      });
      subtitles.on = subtitles.languages.length > 0;
    }

    console.log("props",props);

    let sources;

    if (props.stream !== '') {
      const extractStreamKey = (url) => {
        try {
          const parsed = new URL(url);
          const pathParts = parsed.pathname.split('/').filter(Boolean);
          return pathParts[0] || null;
        } catch {
          return null;
        }
      };
    
      const streamKey = extractStreamKey(props.hls_file);
      const tokenEntry = props.playback_url_token?.[streamKey];
      const finalUrl = tokenEntry
        ? `${props.stream}?${tokenEntry.token}`
        : props.stream;
    
      console.log("🎯 Stream key detectado:", streamKey);
      console.log("🔐 Token aplicado:", tokenEntry?.token);
      console.log("▶️ Final HLS URL:", finalUrl);
    
      sources = [
        {
          src: finalUrl,
          type: 'application/x-mpegURL'
        }
      ];
    } else {
      sources = props.sources;
    }

    const player = videojs(videoElemRef.current, {
      enabledTouchControls: true,
      controls: true,
      autoplay: true,
      muted : false,
      poster: props.poster,
      sources: sources,
      bigPlayButton: true,
      volume: playerStates.playerVolume,
      soundMuted: playerStates.playerSoundMuted,
      theaterMode: playerStates.inTheaterMode,
      videoPreviewThumb: props.previewSprite,
      controlBar: {
        theaterMode: props.hasTheaterMode,
        pictureInPictureToggle: false,
        next: props.hasNextLink,
        previous: props.hasPreviousLink,
      }
    });

    if(props.hls_file !== ''){
      player.volume(0);
      player.muted(true);
    }

    if (subtitles.on) {
      subtitles.languages.forEach((track) => {
        player.addRemoteTextTrack(
          {
            kind: 'subtitles',
            src: track.src,
            srclang: track.srclang,
            label: track.label,
            default: false,
          },
          false
        );
      });
    }
    console.log("props video embed",props.adsTag);

    if(props.adsTag !== null){
      player.ima({
        id: 'content_video_html5_api',
        adTagUrl:
        props.adsTag.url,
      });

    }

    player.on('play', () => {
      if (window._paq) {
        window._paq.push([
          'trackEvent',
          'Video',
          'Play',
          props.info?.title || 'Video sin título',
        ]);
      }
    });

    player.on('ended', () => {
      if (window._paq) {
        window._paq.push([
          'trackEvent',
          'Video',
          'Ended',
          props.info?.title || 'Video sin título',
        ]);
      }
    });

  };

  const unsetPlayer = () => {
    if (playerRef.current) {
      playerRef.current.dispose();
      playerRef.current = null;
    }
  };

  useEffect(() => {
    if (!window.google?.ima) {
      const script = document.createElement('script');
      script.src = 'https://imasdk.googleapis.com/js/sdkloader/ima3.js';
      script.async = true;
      script.onload = () => {
        console.log('✅ Google IMA SDK cargado');
        initPlayer(); // Inicializa después de que el SDK esté listo
      };
      document.body.appendChild(script);
    } else {
      initPlayer();
    }
  
    return () => {
      unsetPlayer();
    };
  }, []);

  return props.errorMessage === null ? (
    <video
      ref={videoElemRef}
      id="content_video"
      className="video-js vjs-mediacms native-dimensions"
    ></video>
  ) : (
    <VideoPlayerError errorMessage={props.errorMessage} />
  );
}

VideoPlayerEmbed.propTypes = {
  playerVolume: PropTypes.string,
  playerSoundMuted: PropTypes.bool,
  videoQuality: PropTypes.string,
  videoPlaybackSpeed: PropTypes.number,
  inTheaterMode: PropTypes.bool,
  siteId: PropTypes.string.isRequired,
  siteUrl: PropTypes.string.isRequired,
  errorMessage: PropTypes.string,
  cornerLayers: PropTypes.object,
  inEmbed: PropTypes.bool.isRequired,
  sources: PropTypes.array.isRequired,
  info: PropTypes.object.isRequired,
  enableAutoplay: PropTypes.bool.isRequired,
  hasTheaterMode: PropTypes.bool.isRequired,
  poster: PropTypes.string,
  adsTag : PropTypes.object,
  hls_file : PropTypes.string,
  previewSprite: PropTypes.object,
  onClickPreviousCallback: PropTypes.func,
  onClickNextCallback: PropTypes.func,
  onPlayerInitCallback: PropTypes.func,
  onStateUpdateCallback: PropTypes.func,
  onUnmountCallback: PropTypes.func,
};

VideoPlayerEmbed.defaultProps = {
  errorMessage: null,
  cornerLayers: {},
};
