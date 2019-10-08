import numpy as np
import torch as th
import torch.nn as nn
from torch.distributions import Normal, Categorical
from gym import spaces

class Distribution(object):
    def __init__(self):
        super(Distribution, self).__init__()

    def log_prob(self, x):
        """
        returns the log likelihood

        :param x: (str) the labels of each index
        :return: ([float]) The log likelihood of the distribution
        """
        raise NotImplementedError

    def kl_div(self, other):
        """
        Calculates the Kullback-Leibler divergence from the given probabilty distribution

        :param other: ([float]) the distribution to compare with
        :return: (float) the KL divergence of the two distributions
        """
        raise NotImplementedError

    def entropy(self):
        """
        Returns shannon's entropy of the probability

        :return: (float) the entropy
        """
        raise NotImplementedError

    def sample(self):
        """
        returns a sample from the probabilty distribution

        :return: (Tensorflow Tensor) the stochastic action
        """
        raise NotImplementedError


class DiagGaussianDistribution(Distribution):
    def __init__(self, action_dim):
        super(DiagGaussianDistribution, self).__init__()
        self.distribution = None
        self.action_dim = action_dim
        self.mean_actions = None
        self.log_std = None

    def proba_distribution_net(self, latent_dim, log_std_init=0.0):
        mean_actions = nn.Linear(latent_dim, self.action_dim)
        # TODO: allow action dependent std
        log_std = nn.Parameter(th.ones(self.action_dim) * log_std_init)
        return mean_actions, log_std

    def proba_distribution(self, mean_actions, log_std, deterministic=False):
        action_std = th.ones_like(mean_actions) * log_std.exp()
        self.distribution = Normal(mean_actions, action_std)
        if deterministic:
            action = self.mode()
        else:
            action = self.sample()
        return action, self

    def mode(self):
        return self.distribution.mean

    def sample(self):
        return self.distribution.rsample()

    def entropy(self):
        return self.distribution.entropy()

    def log_prob_from_params(self, mean_actions, log_std):
        action, _ = self.proba_distribution(mean_actions, log_std)
        log_prob = self.log_prob(action)
        return action, log_prob

    def log_prob(self, action):
        log_prob = self.distribution.log_prob(action)
        if len(log_prob.shape) > 1:
            log_prob = log_prob.sum(axis=1)
        else:
            log_prob = log_prob.sum()
        return log_prob


class SquashedDiagGaussianDistribution(DiagGaussianDistribution):
    def __init__(self, action_dim, epsilon=1e-6):
        super(SquashedDiagGaussianDistribution, self).__init__(action_dim)
        # Avoid NaN (prevents division by zero or log of zero)
        self.epsilon = epsilon
        self.gaussian_action = None

    def proba_distribution(self, mean_actions, log_std, deterministic=False):
        action, _ = super(SquashedDiagGaussianDistribution, self).proba_distribution(mean_actions, log_std, deterministic)
        return action, self

    def mode(self):
        self.gaussian_action = self.distribution.mean
        # Squash the output
        return th.tanh(self.gaussian_action)

    def sample(self):
        self.gaussian_action = self.distribution.rsample()
        return th.tanh(self.gaussian_action)

    def log_prob_from_params(self, mean_actions, log_std):
        action, _ = self.proba_distribution(mean_actions, log_std)
        log_prob = self.log_prob(action, self.gaussian_action)
        return action, log_prob

    def log_prob(self, action, gaussian_action=None):
        # Inverse tanh
        # Naive implementation (not stable): 0.5 * torch.log((1 + x ) / (1 - x))
        # We use numpy to avoid numerical instability
        if gaussian_action is None:
            gaussian_action = th.from_numpy(np.arctanh(action.cpu().numpy())).to(action.device)

        # Log likelihood for a gaussian distribution
        log_prob = super(SquashedDiagGaussianDistribution, self).log_prob(gaussian_action)
        # Squash correction (from original SAC implementation)
        log_prob -= th.sum(th.log(1 - action ** 2 + self.epsilon), dim=1)
        return log_prob


class CategoricalDistribution(Distribution):
    def __init__(self, action_dim):
        super(CategoricalDistribution, self).__init__()
        self.distribution = None
        self.action_dim = action_dim

    def proba_distribution_net(self, latent_dim):
        action_logits = nn.Linear(latent_dim, self.action_dim)
        return action_logits

    def proba_distribution(self, action_logits, deterministic=False):
        self.distribution = Categorical(logits=action_logits)
        if deterministic:
            action = self.mode()
        else:
            action = self.sample()
        return action, self

    def mode(self):
        return th.argmax(self.distribution.probs, dim=1)

    def sample(self):
        return self.distribution.sample()

    def entropy(self):
        return self.distribution.entropy()

    def log_prob_from_params(self, action_logits):
        action, _ = self.proba_distribution(action_logits)
        log_prob = self.log_prob(action)
        return action, log_prob

    def log_prob(self, action):
        log_prob = self.distribution.log_prob(action)
        return log_prob


def make_proba_distribution(action_space):
    """
    Return an instance of Distribution for the correct type of action space

    :param action_space: (Gym Space) the input action space
    :return: (Distribution) the approriate Distribution object
    """
    if isinstance(action_space, spaces.Box):
        assert len(action_space.shape) == 1, "Error: the action space must be a vector"
        return DiagGaussianDistribution(action_space.shape[0])
    elif isinstance(action_space, spaces.Discrete):
        return CategoricalDistribution(action_space.n)
    # elif isinstance(action_space, spaces.MultiDiscrete):
    #     return MultiCategoricalDistribution(action_space.nvec)
    # elif isinstance(action_space, spaces.MultiBinary):
    #     return BernoulliDistribution(action_space.n)
    else:
        raise NotImplementedError("Error: probability distribution, not implemented for action space of type {}."
                                  .format(type(action_space)) +
                                  " Must be of type Gym Spaces: Box, Discrete, MultiDiscrete or MultiBinary.")