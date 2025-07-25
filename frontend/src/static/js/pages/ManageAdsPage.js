import React from 'react';
import PropTypes from 'prop-types';
import { ApiUrlContext } from '../utils/contexts/';
import { PageActions } from '../utils/actions/';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { ManageItemList } from '../components/management-table/ManageItemList/ManageItemList';
import { Page } from './_Page';

function genReqUrl(url, sort, page) {
  const ret = url + '?' + sort + ('' === sort ? '' : '&') + 'page=' + page;
  return ret;
}


export class ManageAdsPage extends Page {
  constructor(props) {
    super(props, 'ads');

    this.state = {
      resultsCount: null,
      requestUrl: ApiUrlContext._currentValue.archive.ads,
      currentPage: 1,
      sortingArgs: '',
      sortBy: 'name',
      ordering: 'desc',
      refresh: 0,
    };

    this.getCountFunc = this.getCountFunc.bind(this);
    this.onTablePageChange = this.onTablePageChange.bind(this);
    this.onColumnSortClick = this.onColumnSortClick.bind(this);
    this.onItemsRemoval = this.onItemsRemoval.bind(this);
    this.onItemsRemovalFail = this.onItemsRemovalFail.bind(this);
  }


  onTablePageChange(newPageUrl, updatedPage) {
    this.setState({
      currentPage: updatedPage,
      requestUrl: genReqUrl(ApiUrlContext._currentValue.archive.ads, this.state.sortingArgs, updatedPage),
    });
  }

  getCountFunc(resultsCount) {
    this.setState({
      resultsCount: resultsCount,
    });
  }

  onColumnSortClick(sort, order) {
    const newArgs = 'sort_by=' + sort + '&ordering=' + order;
    this.setState({
      sortBy: sort,
      ordering: order,
      sortingArgs: newArgs,
      requestUrl: genReqUrl(ApiUrlContext._currentValue.archive.ads, newArgs, this.state.currentPage),
    });
  }

  onItemsRemoval(multipleItems) {
    this.setState(
      {
        resultsCount: null,
        refresh: this.state.refresh + 1,
        requestUrl: ApiUrlContext._currentValue.archive.ads,
      },
      function () {
        if (multipleItems) {
          PageActions.addNotification('The ads deleted successfully.', 'commentsRemovalSucceed');
        } else {
          PageActions.addNotification('The ads deleted successfully.', 'commentRemovalSucceed');
        }
      }
    );
  }

  onItemsRemovalFail(multipleItems) {
    if (multipleItems) {
      PageActions.addNotification('The ads removal failed. Please try again.', 'commentsRemovalFailed');
    } else {
      PageActions.addNotification('The ads removal failed. Please try again.', 'commentRemovalFailed');
    }
  }

  pageContent() {
    return (
      <MediaListWrapper
        className="search-results-wrap items-list-hor"
      >
        <ManageItemList
          pageItems={50}
          manageType={'ads'}
          key={this.state.requestUrl + '[' + this.state.refresh + ']'}
          itemsCountCallback={this.getCountFunc}
          requestUrl={this.state.requestUrl}
          onPageChange={this.onTablePageChange}
          sortBy={this.state.sortBy}
          ordering={this.state.ordering}
          onRowsDelete={this.onItemsRemoval}
          onRowsDeleteFail={this.onItemsRemovalFail}
          onClickColumnSort={this.onColumnSortClick}
        />
      </MediaListWrapper>
    );
  }
}

ManageAdsPage.propTypes = {
  title: PropTypes.string.isRequired,
};

ManageAdsPage.defaultProps = {
  title: 'Manage ads',
};
