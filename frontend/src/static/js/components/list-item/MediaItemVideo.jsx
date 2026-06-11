import React from 'react';
import PropTypes from 'prop-types';
import { useMediaItem } from '../../utils/hooks/';
import { PositiveIntegerOrZero } from '../../utils/helpers/';
import { MediaDurationInfo } from '../../utils/classes/';
import { MediaPlaylistOptions } from '../media-playlist-options/MediaPlaylistOptions.jsx';
import { MediaItemVideoPlayer, MediaItemDuration, MediaItemVideoPreviewer, MediaItemPlaylistIndex, itemClassname } from './includes/items/';
import { MediaItem } from './MediaItem';

export function MediaItemVideo(props) {

  const type = props.type;

  const [titleComponent, descriptionComponent, thumbnailUrl, UnderThumbWrapper, editMediaComponent, metaComponents] =
    useMediaItem({ ...props, type });

  const _MediaDurationInfo = new MediaDurationInfo();

  const durationSeconds = 'number' === typeof props.duration && isFinite(props.duration) ? props.duration : null;

  if (null !== durationSeconds) {
    _MediaDurationInfo.update(durationSeconds);
  }

  const duration = null === durationSeconds ? '' : _MediaDurationInfo.ariaLabel();
  const durationStr = null === durationSeconds ? '' : _MediaDurationInfo.toString();
  const durationISO8601 = null === durationSeconds ? '' : _MediaDurationInfo.ISO8601();

  function videoViewerComponent() {
    return <MediaItemVideoPlayer mediaPageLink={props.link} />;
  }

  function thumbnailComponent() {
    const attr = {
      key: 'item-thumb',
      href: props.link,
      title: props.title,
      tabIndex: '-1',
      'aria-hidden': true,
      className: 'item-thumb' + (!thumbnailUrl && !props.isLiveStream ? ' no-thumb' : ''),
      style: !thumbnailUrl ? null : { backgroundImage: "url('" + thumbnailUrl + "')" },
    };

    return (
      <a {...attr}>
        {props.isLiveStream && !thumbnailUrl ? (
          <span className="item-live-preview" style={{ '--live-accent': props.livePreview.accent }}>
            <span className="item-live-preview-band item-live-preview-band-one"></span>
            <span className="item-live-preview-band item-live-preview-band-two"></span>
            <span className="item-live-preview-status">
              <span></span>
              {props.isLiveOnline ? 'EN VIVO' : 'OFFLINE'}
            </span>
            <strong>{props.livePreview.initials}</strong>
            <em>{props.livePreview.title}</em>
            <small>{props.isLiveOnline ? 'Streaming' : 'Sin señal'}</small>
          </span>
        ) : null}
        {props.isLiveStream ? (
          <span className={`item-live-badge ${props.isLiveOnline ? 'item-live-badge-on' : 'item-live-badge-off'}`}>
            <span>{props.isLiveOnline ? 'EN VIVO' : 'OFFLINE'}</span>
          </span>
        ) : props.inPlaylistView || !durationStr ? null : (
          <MediaItemDuration ariaLabel={duration} time={durationISO8601} text={durationStr} />
        )}
        {props.isLiveStream || props.inPlaylistView || props.inPlaylistPage ? null : (
          <MediaItemVideoPreviewer url={props.preview_thumbnail} />
        )}
      </a>
    );
  }

  function playlistOrderNumberComponent() {
    return props.hidePlaylistOrderNumber ? null : (
      <MediaItemPlaylistIndex
        index={props.playlistOrder}
        inPlayback={props.inPlaylistView}
        activeIndex={props.playlistActiveItem}
      />
    );
  }

  function playlistOptionsComponent() {
    if (props.hidePlaylistOptions) {
      return null;
    }

    let mediaId = props.link.split('=')[1];
    mediaId = mediaId.split('&')[0];
    return (
      <MediaPlaylistOptions key="options" media_id={mediaId} playlist_id={props.playlist_id} />
    );
  }

  function liveStateComponent() {
    if (!props.isLiveStream) {
      return null;
    }

    return (
      <span className={`item-live-label ${props.isLiveOnline ? 'item-live-label-on' : 'item-live-label-off'}`}>
        <strong>{props.isLiveOnline ? 'LIVE' : 'OFFLINE'}</strong>
        <span>{props.isLiveOnline ? 'Transmisión en vivo' : 'Sin señal'}</span>
      </span>
    );
  }

  const containerClassname = itemClassname(
    'item ' + type + '-item',
    props.class_name.trim(),
    props.playlistOrder === props.playlistActiveItem
  );

  return (
    <div className={containerClassname}>
      {playlistOrderNumberComponent()}

      <div className="item-content">
        {editMediaComponent()}

        {props.hasMediaViewer ? videoViewerComponent() : thumbnailComponent()}

        <UnderThumbWrapper title={props.title} link={props.link}>
          {titleComponent()}
          {liveStateComponent()}
          {metaComponents()}
          {descriptionComponent()}
        </UnderThumbWrapper>
      </div>

      {playlistOptionsComponent()}
    </div>
  );
}

MediaItemVideo.propTypes = {
  ...MediaItem.propTypes,
  type: PropTypes.string.isRequired,
  duration: PositiveIntegerOrZero,
  hidePlaylistOptions: PropTypes.bool,
  hasMediaViewer: PropTypes.bool,
  hasMediaViewerDescr: PropTypes.bool,
  isLiveStream: PropTypes.bool,
  isLiveOnline: PropTypes.bool,
  livePreview: PropTypes.shape({
    title: PropTypes.string,
    initials: PropTypes.string,
    accent: PropTypes.string,
  }),
  playlist_id: PropTypes.string,
};

MediaItemVideo.defaultProps = {
  ...MediaItem.defaultProps,
  type: 'video',
  duration: 0,
  hidePlaylistOptions: true,
  hasMediaViewer: false,
  hasMediaViewerDescr: false,
  isLiveStream: false,
  isLiveOnline: false,
  livePreview: {
    title: 'Señal en vivo',
    initials: 'LV',
    accent: '#ff121f',
  },
};
