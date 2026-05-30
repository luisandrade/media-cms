import React from 'react';
import PropTypes from 'prop-types';
import { ApiUrlContext } from '../utils/contexts/';
import { LinksContext } from '../utils/contexts/';
import { format, register } from 'timeago.js';
import es from 'timeago.js/lib/lang/es';
import { translateString } from '../utils/helpers/';
import { MaterialIcon, SpinnerLoader } from '../components/_shared';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { Page } from './_Page';
import './ManageStatisticsPage.scss';

register('es', es);

const STAT_CARDS = [
  {
    key: 'total_videos',
    icon: 'smart_display',
    label: 'Total videos',
    className: 'videos',
  },
  {
    key: 'total_members',
    icon: 'groups',
    label: 'Total members',
    className: 'members',
  },
  {
    key: 'total_categories',
    icon: 'category',
    label: 'Total categories',
    className: 'categories',
  },
  {
    key: 'total_sales',
    icon: 'payments',
    label: 'Total sales',
    className: 'sales',
  },
];

function formatCount(value) {
  return new Intl.NumberFormat().format('number' === typeof value ? value : 0);
}

function formatCompactCount(value) {
  return new Intl.NumberFormat('en', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format('number' === typeof value ? value : 0);
}

function formatActivityDate(value) {
  return format(new Date(value), 'es');
}

function activityActionText(item) {
  if ('comment' === item.kind) {
    return `${translateString('Commented on')} "${item.media_title}"`;
  }

  return translateString('Uploaded a video');
}

function topRatedMeta(item) {
  return [item.year, item.category].filter(Boolean).join(' • ');
}

export class ManageStatisticsPage extends Page {
  constructor(props) {
    super(props, 'manage-statistics');

    this.state = {
      hasError: false,
      isLoading: true,
      stats: null,
    };

    this.loadStatistics = this.loadStatistics.bind(this);
  }

  componentDidMount() {
    this.loadStatistics();
  }

  async loadStatistics() {
    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.statistics, {
        credentials: 'same-origin',
      });

      if (!response.ok) {
        throw new Error('Unable to load statistics');
      }

      const stats = await response.json();

      this.setState({
        hasError: false,
        isLoading: false,
        stats,
      });
    } catch (error) {
      this.setState({
        hasError: true,
        isLoading: false,
        stats: null,
      });
    }
  }

  pageContent() {
    const { hasError, isLoading, stats } = this.state;

    return (
      <MediaListWrapper className="items-list-hor manage-statistics-wrapper">
        <div className="manage-statistics-page">
          <div className="manage-statistics-head">
            <h1>Dashboard</h1>
          </div>

          <div className="manage-statistics-content">
            {isLoading ? (
              <div className="manage-statistics-state">
                <SpinnerLoader size="large" />
              </div>
            ) : hasError ? (
              <div className="manage-statistics-state manage-statistics-state-error">
                {translateString('Unable to load statistics')}
              </div>
            ) : (
              <>
                <div className="manage-statistics-grid">
                  {STAT_CARDS.map((card) => (
                    <article
                      key={card.key}
                      className={"manage-statistics-card manage-statistics-card-" + card.className}
                    >
                      <div className="manage-statistics-card-icon">
                        <MaterialIcon type={card.icon} />
                      </div>
                      <div className="manage-statistics-card-value">{formatCount(stats ? stats[card.key] : 0)}</div>
                      <div className="manage-statistics-card-label">{translateString(card.label)}</div>
                    </article>
                  ))}
                </div>

                <div className="manage-dashboard-lower-grid">
                  <section className="manage-top-categories">
                    <div className="manage-top-categories-head">
                      <div className="manage-top-categories-title">
                        <span className="manage-top-categories-title-icon">
                          <MaterialIcon type="grid_view" />
                        </span>
                        <h2>{translateString('Top categories')}</h2>
                      </div>
                      <a href={LinksContext._currentValue.archive.categories} className="manage-top-categories-link">
                        {translateString('View all')}
                      </a>
                    </div>

                    <div className="manage-top-categories-grid">
                      {(stats.top_categories || []).map((category) => (
                        <a key={category.url + category.title} href={category.url} className="manage-top-categories-item">
                          <span className="manage-top-categories-item-icon">
                            <MaterialIcon type="category" />
                          </span>
                          <span className="manage-top-categories-item-title">{category.title}</span>
                        </a>
                      ))}
                    </div>
                  </section>

                  <section className="manage-recent-activity">
                    <div className="manage-recent-activity-head">
                      <div className="manage-recent-activity-title">
                        <span className="manage-recent-activity-title-icon">
                          <MaterialIcon type="history" />
                        </span>
                        <h2>{translateString('Recent activity')}</h2>
                      </div>
                      <a href={LinksContext._currentValue.manage.media} className="manage-recent-activity-link">
                        {translateString('View all')}
                      </a>
                    </div>

                    <div className="manage-recent-activity-table">
                      <div className="manage-recent-activity-row manage-recent-activity-row-head">
                        <div>{translateString('User')}</div>
                        <div>{translateString('Action')}</div>
                        <div>{translateString('Date')}</div>
                        <div>{translateString('Status')}</div>
                      </div>

                      {(stats.recent_activity || []).map((item, index) => (
                        <div key={item.kind + item.user_name + item.date + index} className="manage-recent-activity-row">
                          <div className="manage-recent-activity-user">
                            <span className="manage-recent-activity-user-thumb">
                              {item.user_thumbnail ? (
                                <img src={item.user_thumbnail} alt={item.user_name} />
                              ) : (
                                <MaterialIcon type="person" />
                              )}
                            </span>
                            <span className="manage-recent-activity-user-meta">
                              <span className="manage-recent-activity-user-name">{item.user_name}</span>
                            </span>
                          </div>

                          <div className="manage-recent-activity-action">{activityActionText(item)}</div>
                          <div className="manage-recent-activity-date">{formatActivityDate(item.date)}</div>
                          <div className="manage-recent-activity-status">
                            <span
                              className={
                                'manage-recent-activity-badge ' +
                                ('Approved' === item.status
                                  ? 'manage-recent-activity-badge-approved'
                                  : 'manage-recent-activity-badge-pending')
                              }
                            >
                              {translateString(item.status)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>

                <section className="manage-top-rated">
                  <div className="manage-top-rated-head">
                    <div className="manage-top-rated-title">
                      <span className="manage-top-rated-title-icon">
                        <MaterialIcon type="emoji_events" />
                      </span>
                      <h2>{translateString('Top rated')}</h2>
                    </div>
                    <a href={LinksContext._currentValue.manage.media} className="manage-top-rated-link">
                      {translateString('View all')}
                    </a>
                  </div>

                  <div className="manage-top-rated-table">
                    <div className="manage-top-rated-row manage-top-rated-row-head">
                      <div>{translateString('Video')}</div>
                      <div>{translateString('views')}</div>
                      <div>{translateString('Likes')}</div>
                      <div>{translateString('Rank')}</div>
                    </div>

                    {(stats.top_rated_videos || []).map((item) => {
                      const meta = topRatedMeta(item);

                      return (
                        <a key={item.rank + item.title} href={item.url} className="manage-top-rated-row manage-top-rated-row-link">
                          <div className="manage-top-rated-video">
                            <span className="manage-top-rated-thumb">
                              {item.thumbnail_url ? (
                                <img src={item.thumbnail_url} alt={item.title} />
                              ) : (
                                <MaterialIcon type="smart_display" />
                              )}
                            </span>

                            <span className="manage-top-rated-video-meta">
                              <span className="manage-top-rated-video-title">{item.title}</span>
                              {meta ? <span className="manage-top-rated-video-subtitle">{meta}</span> : null}
                            </span>
                          </div>

                          <div className="manage-top-rated-views">{formatCompactCount(item.views)}</div>
                          <div className="manage-top-rated-likes">
                            <MaterialIcon type="star" />
                            <span>{formatCount(item.likes)}</span>
                          </div>
                          <div className="manage-top-rated-rank">#{item.rank}</div>
                        </a>
                      );
                    })}
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      </MediaListWrapper>
    );
  }
}

ManageStatisticsPage.propTypes = {
  title: PropTypes.string,
};

ManageStatisticsPage.defaultProps = {
  title: 'Statistics',
};