import React, { useState } from 'react';
import { ApiUrlConsumer } from '../utils/contexts/';
import { PageStore } from '../utils/stores/';
import { Page } from './Page';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { LazyLoadItemListAsync } from '../components/item-list/LazyLoadItemListAsync.jsx';
import { translateString } from '../utils/helpers/';

interface PurchasesPageProps {
  id?: string;
  title?: string;
}

export const PurchasesPage: React.FC<PurchasesPageProps> = ({
  id = 'purchases',
  title = translateString('My purchases'),
}) => {
  const [resultsCount, setResultsCount] = useState<number | null>(null);

  return (
    <Page id={id}>
      <ApiUrlConsumer>
        {(apiUrl) => (
          <MediaListWrapper
            title={title + (null !== resultsCount ? ' (' + resultsCount + ')' : '')}
            className="search-results-wrap items-list-hor"
          >
            <LazyLoadItemListAsync
              singleLinkContent={false}
              horizontalItemsOrientation={true}
              itemsCountCallback={setResultsCount}
              requestUrl={apiUrl.user.purchases}
              hideViews={!PageStore.get('config-media-item').displayViews}
              hideAuthor={!PageStore.get('config-media-item').displayAuthor}
              hideDate={!PageStore.get('config-media-item').displayPublishDate}
            />
          </MediaListWrapper>
        )}
      </ApiUrlConsumer>
    </Page>
  );
};
