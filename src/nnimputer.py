import numpy as np


from hyperopt import hp, Trials, fmin, tpe
from datetime import datetime


class NNImputer(object):
    def __init__(
        self,
        nn_type="ii",
        eta_axis=0,
        eta_space=hp.uniform('eta', 0, 1),
        search_algo=tpe.suggest,
        k=None,
        rand_seed=None,
    ):
        """
        Parameters:
        -----------
        nn_type : string in ("ii", "uu")
                  represents the type of nearest neighbors to use
                  "ii" is "item-item" nn, which is column-wise
                  "uu" is "user-user" nn, which is row-wise. The default value is
                  "ii". 
        eta_axis : integer in [0, 1].
                   The axis to compute etas.
                   Default is 0. 
                   - If 0, then etas are computed for every row 
                   - If 1, then etas are computed for every column.
                   - If -1, then a single eta is computed using cv
        eta_space : a hyperopt hp search space
                    for example: hp.uniform('eta', 0, 1). If no eta_space is inputted,
                    then this example will be the default search space.
        search_algo : a hyperopt algorithm
                      for example: tpe.suggest, default is tpe.suggest.
        k : integer > 1, the number of folds in k-fold cross validation over.
            If k = None (default), the LOOCV is used. 
        rand_seed : the random seed to be used for reproducible results. 
                    If None is used (default), then the system time is used (not reproducible)
        """
        self.nn_type = nn_type
        self.eta_axis = eta_axis
        self.eta_space = eta_space
        self.search_algo = search_algo
        self.k = k
        self.rand_seed = rand_seed

    # should introduce validation for parameter ranges
    def set_etaspace(self, eta_space):
        """
        Parameters:
        -----------
        eta_space : a hyperopt parameter space object (hyperopt.uniform, hyperopt.loguniform, etc.)
        """
        self.eta_space = eta_space

    # Helpers / data validation
    def _validate_inputs(self, Z: np.array, M: np.array):
        if len(Z.shape) != 4:
            raise ValueError(
                "Input shape of data array should have 4 dimensions but {} were found".format(
                    str(len(Z.shape))
                )
            )
        if len(M.shape) != 2:
            raise ValueError(
                "Input shape of masking matrix should have 2 dimensions but {} were found".format(
                    str(len(M.shape))
                )
            )
        N, T, n, d = Z.shape
        N_q, T_q = M.shape
        if N != N_q or T != T_q:
            raise ValueError(
                "Masking matrix of dimension {} x {} was expected but matrix of dimension {} x {} was found instead"
            ).format(str(N), str(T), str(N_q), str(T_q))
        if np.nansum(M == 1) == 0:
            raise ValueError("All values are masked.")

    # "Abstract" methods -> these should be overridden by any subclasses.
    def estimate(self, inds=None, *args, **kwargs):
        # if inds is not None, only estimate inds indices in Z
        raise ValueError(
            "{}.estimate is unimplemented and needs to be overridden in a subclass".format(
                self.__name__
            )
        )

    def distances(self, *args, **kwargs):
        raise ValueError(
            "{}.distances is unimplemented and needs to be overridden in a subclass".format(
                self.__name__
            )
        )

    def avg_error(self, ests, truth, *args, **kwargs):
        """
        Average error over a 1d array-like of entries
        """
        raise ValueError(
            "{}.avg_error is unimplemented and needs to be overridden in a subclass".format(
                self.__name__
            )
        )

    def entry_error(self, est, truth, *args, **kwarags):
        """
        Error for a single entry
        """
        raise ValueError(
            "{}.entry_error is unimplemented and needs to be overridden in a subclass".format(
                self.__name__
            )
        )

    # Common Code
    def cross_validate(self, Z, M, inds, dists, eta, *args, **kwargs):
        """
        Given a neighborhood radius eta, compute the average validation error
        over k folds

        Parameters:
        ----------
        Z : N x T x n x d
        M : N x T
        inds : scalar or 1d array like
        dists : N x N or T x T (relies on search axis)
        eta : the neighborhood threshold (radius)

        Returns:
        ----------
        avg_error : the average error of estimates over k validation folds
        """
        if not (self.rand_seed is None):
            np.random.seed(seed=self.rand_seed)
        else:
            np.random.seed(seed=datetime.now().timestamp())

        if self.eta_axis == -1:
            obvs_inds = np.nonzero(M == 1)
            sel_inds = np.arange(len(obvs_inds[0]))
            k = self.k if self.k is not None else len(sel_inds)
            np.random.shuffle(sel_inds)
            fold_sels = np.array_split(sel_inds, k)
            
            tot_error = 0
            final_k = k
            for j in range(k):
                cv_mask = M.copy()
                cv_Z = Z.copy()
                holdout_inds = (obvs_inds[0][fold_sels[j]], obvs_inds[1][fold_sels[j]])
                ground_truth = cv_Z[holdout_inds]
                cv_Z[holdout_inds] = np.nan
                cv_mask[holdout_inds] = 0
                flattened_inds = []
                for b in range(len(holdout_inds[0])):
                    flattened_inds.append((holdout_inds[0][b], holdout_inds[1][b]))
                cv_Z_est = self.estimate(
                    cv_Z, cv_mask, inds = flattened_inds, dists = dists, eta = eta
                )
                final_ests = []
                for c, d in flattened_inds:
                    final_ests.append(cv_Z_est[c][d])
                err = self.avg_error(
                    final_ests, ground_truth, inds=np.arange(0, len(holdout_inds[0]))
                )
            if not np.isnan(err):
                notnan = True
                tot_error += err
            else:
                final_k -= 1
            # none of the folds returned nonnan error
            if final_k == 0:
                return np.inf
                # currently discard folds with nan error
            return tot_error / final_k


        # eta search per row (default)
        elif self.eta_axis == 0:
            obvs_inds = np.nonzero(M[inds] == 1)[0]
        elif self.eta_axis == 1:
            obvs_inds = np.nonzero(M[:, inds] == 1)[0]

        # shuffle inds

        np.random.shuffle(obvs_inds)

        # split obvs inds into k folds
        if self.k is None:
            k = len(obvs_inds)
        else:
            k = self.k
        folds = np.array_split(obvs_inds, k, axis=0)

        tot_error = 0
        final_k = k
        for j in range(k):
            cv_mask = M.copy()
            cv_Z = Z.copy()
            folds_inds = folds[j]
            if self.eta_axis == 0:
                # cv over a row
                ground_truth = cv_Z[inds, folds_inds]
                cv_Z[inds, folds_inds] = np.nan
                cv_mask[inds, folds_inds] = 0
                recon_inds = np.array([(inds, x) for x in folds_inds])
                cv_Z_est = self.estimate(
                    cv_Z, cv_mask, inds=recon_inds, dists=dists, eta=eta
                )
                final_ests = [cv_Z_est[inds][i] for i in folds_inds]

            else:
                # cv over a col
                ground_truth = cv_Z[folds_inds, inds]
                cv_Z[folds_inds, inds] = np.nan
                cv_mask[folds_inds, inds] = 0
                recon_inds = np.array([(x, inds) for x in folds_inds])
                cv_Z_est = self.estimate(
                    cv_Z, cv_mask, inds=recon_inds, dists=dists, eta=eta
                )
                final_ests = [cv_Z_est[inds][i] for i in folds_inds]

            # compute avg error over estimates
            err = self.avg_error(
                final_ests, ground_truth, inds=np.arange(0, len(folds_inds))
            )

            # TODO: think about this behavior - if fold error is nan, what to do?
            if not np.isnan(err):
                notnan = True
                tot_error += err
            else:
                final_k -= 1
            # none of the folds returned nonnan error
        if final_k == 0:
            return np.inf
            # currently discard folds with nan error
        return tot_error / final_k

    def search_eta(
        self,
        Z,
        M,
        inds,
        dists,
        max_evals=200,
        ret_trials=False,
        verbose=True,
        *args,
        **kwargs
    ):
        """
        Search for an optimal eta using cross validation on
        the observed data.

        Parameters:
        ----------
        Z : array with shape (N, T, n, d)
        M : array with shape (N, T)
        inds : 1d array-like or scalar, the indices to perform cross-valdiation over.
               inds indexes into axis specified by s. If 1d array, then len(inds) rows/cols
               are selected for cross-validation.
        dists : distances between rows/cols.

        TBC ....
        """

        def obj(eta):
            return self.cross_validate(Z, M, inds, dists, eta)

        trials = Trials()
        best_eta = fmin(
            fn=obj,
            verbose=verbose,
            space=self.eta_space,
            algo=self.search_algo,
            max_evals=max_evals,
            trials=trials,
        )

        return best_eta["eta"] if not ret_trials else (best_eta["eta"], trials)
    
    def _one_eta(self, Z : np.array, M : np.array, dists):
        """
        Z : N x T x n x d
        M : N x T
        dists : columnwise or row-wise distances

        Returns:
        eta : a tuned eta
        """

    def _axis_eta(self, Z: np.array, M: np.array, inds, dists):
        """
        Z : N x T x n x d
        M : N x T
        inds : list of indices to estimate
        dists : columnwise distances

        Returns:
        etas : array of size N
        """
        N, T, _, _ = Z.shape
        eta_len = N if self.eta_axis == 0 else T
        etas = np.full([eta_len], np.nan)

        axis_inds = inds[self.eta_axis]
        unq_axis_inds = np.unique(axis_inds)

        for i in range(unq_axis_inds):
            etas[i] = self.search_eta(Z, M, i, dists)

        return etas

    def _col_eta(self, Z: np.array, M: np.array, inds, dists):
        """
        Z : N x T x n x d
        M : N x T
        inds : list of indices to estimate
        dists : columnwise distances

        Returns:
        etas : array of size T
        """
        _, T, _, _ = Z.shape
        etas = np.full([T], np.nan)
        for i in range(T):
            # we do not sample split for time complexity reasons
            # s_Mask = M.copy()
            # s_Mask[:, i] = 0
            # cv_dists = self.distances(Z, s_Mask, axis=0)
            etas[i] = self.search_eta(Z, M, i, dists)
        return etas

    # TODO: support for user-item NN, block eta tuning
    def tune_transform(
        self, Z: np.array, M: np.array, inds = None, eta_type = "axis", eta_axis=0, num_blocks = 2, *args, **kwargs
    ):
        """
        Estimate the specified entries of Z using distributional nearest neighbors.

        Parameters:
        ----------
        Z : N x T x n x d tensor (type: np.array)
        M : N x T masking matrix (type: np.array)
        inds : array-like of tuples (i, t) that index Z (optional)
               Default: None. Represents the indices to be estimated by the algorithm.
               Unmasked (M_it = 1) entries are used to estimate the entries in inds.
               If inds = None, then all masked (M_it = 0) are estimated.
        eta_type : string ("axis" or "block")
                   if "axis", then an eta is tuned for each row/col (specified by eta_type).
                   if "block", then an eta is tuned by splitting each
        dists : array-like of shape (a, a) (optional)
                a = N if self.nn_type is "uu" and a = T if self.nn_type is "ii"
                Default: None. If None, then distances are computed prior to estimation
        eta_axis : int (0 or 1), optional
                   The axis to compute etas.
                   Default is 0. 
                   If eta_type = "axis".
                   - If 0, then etas are computed for every row 
                   - If 1, then etas are computed for every column.
                   If eta_type = "block":
                   - If 0 then Z is split row-wise into num_blocks sections
                   - If 1 then Z is split col-wise into num_blocks sections 
        num_blocks : the number of blocks to compute eta over. Default is 2.
                     If eta_type = "axis", parameter is ignored.
        Returns:
        ----------
        Z_hat : N x T x n x d tensor (type np.array)
        """
        self._validate_inputs(Z, M)

        N, T, n, d = Z.shape

        if inds is None:
            inds = np.nonzero(M == 1)

        full_dists = self.distances(Z, M, nn_type=self.nn_type)

        # axis type and row
        if eta_type == "axis" and eta_axis == 0:
            etas = self._row_eta(Z, M, inds)
        elif eta_type == "axis" and eta_axis == 1:
            etas = self._col_eta(Z, M, inds)
        elif eta_type == "block" and eta_axis == 0:
            etas = None
        elif eta_type == "block" and eta_axis == 1:
            etas == None

        Z_hat = self.estimate(Z, M, full_dists, etas, self.nn_type)

        # compute distances using self.distances (default col).
        #  - distances should be sample split per row
        # tune eta using cross validation
        #   defaults: even-odd row eta tuning, item-item neighbors, LOOCV
        #   custom: cv splitting, k-fold cv, col tuning, block tuning, user-user neighbors
        # for each eta, estimate row using self.estimate.

        return Z_hat

    # other funcs:
    # - tune (only returned tuned etas)
    # estimate : implemented in subclasses
